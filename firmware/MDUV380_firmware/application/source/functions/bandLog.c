/* Band occupancy logger - see bandLog.h. */
#include "functions/bandLog.h"

#if defined(ENABLE_BAND_LOG)

#include <string.h>
// uiGlobals.h first: it defines time_t_custom, which gps.h uses but does not
// include a definition for.
#include "user_interface/uiGlobals.h"
#include "hardware/SPI_Flash.h"
#include "functions/settings.h"
#include "interfaces/gps.h"

// Same region gps.c logs NMEA into: the last 2 MB of a 16 MB part. Anything
// smaller has no room to spare, so logging is simply unavailable there.
#define BAND_LOG_START_ADDRESS   (14 * 1024 * 1024)
#define BAND_LOG_MEM_SIZE        (2 * 1024 * 1024)
#define BAND_LOG_SECTOR_SIZE     4096

static uint32_t writeOffset = 0;
static bool     running = false;

void bandLogInit(void)
{
	writeOffset = 0;
	running = false;
}

bool bandLogIsRunning(void)
{
	return running;
}

uint32_t bandLogBytesUsed(void)
{
	return writeOffset;
}

uint32_t bandLogCapacity(void)
{
	return BAND_LOG_MEM_SIZE;
}

bandLogResult_t bandLogStart(void)
{
	// The NMEA logger writes a raw character stream into this same area with no
	// framing of its own. Interleaving the two would leave neither readable, so
	// refuse rather than silently corrupt a track log the user is collecting.
	if (SETTINGS_GPS_MODE_GET(nonVolatileSettings) == GPS_MODE_ON_LOG)
	{
		return BAND_LOG_ERR_GPS_LOGGING;
	}

	if (flashChipPartNumber != 0x4018)   // 16 MB part only
	{
		return BAND_LOG_ERR_FLASH_SIZE;
	}

	if (SPI_Flash_eraseSector(BAND_LOG_START_ADDRESS) == false)
	{
		return BAND_LOG_ERR_ERASE;
	}

	writeOffset = 0;
	running = true;
	return BAND_LOG_OK;
}

void bandLogStop(void)
{
	running = false;
}

bool bandLogWriteSweep(const uint8_t *samples, uint8_t numBins,
		uint32_t centreFreq, uint32_t stepFreq, uint8_t mode)
{
	bandLogHeader_t hdr;
	uint32_t recordLen;
	uint32_t addr;

	if ((running == false) || (samples == NULL) || (numBins == 0))
	{
		return false;
	}

	recordLen = sizeof(bandLogHeader_t) + numBins;

	// Wrap before writing, not after, so a record is never split across the end
	// of the region: a reader that finds the magic can always trust the length
	// that follows it.
	if ((writeOffset + recordLen) > BAND_LOG_MEM_SIZE)
	{
		writeOffset = 0;
	}

	// Erase lazily, one sector ahead of the write. Erasing the whole 2 MB up
	// front would take minutes and wear the part for a log that may only ever
	// hold a few records.
	if ((writeOffset % BAND_LOG_SECTOR_SIZE) == 0)
	{
		if (SPI_Flash_eraseSector(BAND_LOG_START_ADDRESS + writeOffset) == false)
		{
			return false;
		}
	}
	else if (((writeOffset + recordLen) / BAND_LOG_SECTOR_SIZE) !=
			(writeOffset / BAND_LOG_SECTOR_SIZE))
	{
		// This record straddles into the next sector; that sector must be blank
		// before any of it is written.
		uint32_t nextSector = ((writeOffset / BAND_LOG_SECTOR_SIZE) + 1) * BAND_LOG_SECTOR_SIZE;

		if (nextSector >= BAND_LOG_MEM_SIZE)
		{
			writeOffset = 0;
			nextSector = 0;
		}

		if (SPI_Flash_eraseSector(BAND_LOG_START_ADDRESS + nextSector) == false)
		{
			return false;
		}
	}

	memset(&hdr, 0, sizeof(hdr));
	hdr.magic      = BAND_LOG_MAGIC;
	hdr.version    = BAND_LOG_VERSION;
	hdr.numBins    = numBins;
	hdr.mode       = mode;
	hdr.epoch      = (uint32_t)uiDataGlobal.dateTimeSecs;
	hdr.centreFreq = centreFreq;
	hdr.stepFreq   = stepFreq;

	if ((gpsData.Status & GPS_STATUS_HAS_FIX) != 0)
	{
		hdr.flags |= BAND_LOG_FLAG_HAS_FIX;

		if ((gpsData.Status & GPS_STATUS_3D_FIX) != 0)
		{
			hdr.flags |= BAND_LOG_FLAG_3D_FIX;
		}

		// gpsData.Latitude/Longitude are the packed NMEA form; the HiRes pair is
		// plain decimal degrees. Stored as 1e-7 deg fixed point so a reader
		// needs no knowledge of the NMEA packing - and signed, so the southern
		// and western hemispheres survive the trip.
		hdr.latitude  = (int32_t)(gpsData.LatitudeHiRes * 10000000.0);
		hdr.longitude = (int32_t)(gpsData.LongitudeHiRes * 10000000.0);
	}

	addr = BAND_LOG_START_ADDRESS + writeOffset;

	if (SPI_Flash_write(addr, (uint8_t *)&hdr, sizeof(hdr)) == false)
	{
		return false;
	}

	// Straight out of the sweep's own buffer - no copy, so no stack cost for
	// what would otherwise be a 160 byte local on a target with a 1.5 KB stack.
	if (SPI_Flash_write((addr + sizeof(hdr)), (uint8_t *)samples, numBins) == false)
	{
		return false;
	}

	writeOffset += recordLen;
	return true;
}

#endif // ENABLE_BAND_LOG
