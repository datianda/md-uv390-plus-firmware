/*
 * Band occupancy logger.
 *
 * The sweep already measures 160 RSSI bins every pass and then throws them away
 * once they have scrolled off the waterfall. The radio also knows the time (it
 * has a real RTC) and, on a GPS model, where it is. Writing those three things
 * together turns the sweep into a portable band survey: what was busy, when,
 * and from where - which is the question you actually have when siting a
 * repeater, chasing interference, or working out whether a satellite downlink
 * was audible from a given spot.
 *
 * Storage is the last 2 MB of the 16 MB SPI flash, which the firmware already
 * treats as a log area (gps.c logs NMEA there in GPS_MODE_ON_LOG). It is a
 * cyclic buffer: oldest records are overwritten, so logging can be left on.
 *
 * *** The NMEA logger uses the SAME region. Only one of the two may be enabled
 * at a time - bandLogStart() refuses while GPS_MODE_ON_LOG is selected. ***
 *
 * Costs no MCU RAM beyond a handful of bytes: the sample block is written
 * straight out of the sweep's existing static buffer, so nothing is copied.
 */
#ifndef _OPENGD77_BAND_LOG_H_
#define _OPENGD77_BAND_LOG_H_

#include <stdint.h>
#include <stdbool.h>

#if defined(ENABLE_BAND_LOG)

#define BAND_LOG_MAGIC        0x474F4C42U   /* "BLOG", little-endian */
#define BAND_LOG_VERSION      1

/* Header flags */
#define BAND_LOG_FLAG_HAS_FIX   (1 << 0)
#define BAND_LOG_FLAG_3D_FIX    (1 << 1)

/* Written immediately before the sample block, which is numBins bytes long. */
typedef struct __attribute__((packed))
{
	uint32_t magic;        /* BAND_LOG_MAGIC                                  */
	uint8_t  version;      /* BAND_LOG_VERSION                                */
	uint8_t  flags;        /* BAND_LOG_FLAG_*                                 */
	uint8_t  numBins;      /* samples that follow this header                 */
	uint8_t  mode;         /* trxGetMode() at capture time                    */
	uint32_t epoch;        /* uiDataGlobal.dateTimeSecs (UTC)                 */
	uint32_t centreFreq;   /* 10 Hz units, as the rest of the firmware counts */
	uint32_t stepFreq;     /* 10 Hz units per bin                             */
	int32_t  latitude;     /* 1e-7 deg, 0 when no fix                         */
	int32_t  longitude;    /* 1e-7 deg, 0 when no fix                         */
} bandLogHeader_t;

/* Why a start attempt failed. Reported over USB so the host can say which of
 * these it was rather than guess at the most likely one. */
typedef enum
{
	BAND_LOG_OK = 0,
	BAND_LOG_ERR_GPS_LOGGING = 1,  /* GPS_MODE_ON_LOG owns the same flash area */
	BAND_LOG_ERR_FLASH_SIZE  = 2,  /* not the 16 MB part                       */
	BAND_LOG_ERR_ERASE       = 3   /* the first sector erase failed            */
} bandLogResult_t;

void bandLogInit(void);
bool bandLogIsRunning(void);

/* Erases the first sector and starts at the beginning. */
bandLogResult_t bandLogStart(void);
void bandLogStop(void);

/* One sweep pass. `samples` is numBins bytes, normally the sweep's own buffer. */
bool bandLogWriteSweep(const uint8_t *samples, uint8_t numBins,
		uint32_t centreFreq, uint32_t stepFreq, uint8_t mode);

uint32_t bandLogBytesUsed(void);
uint32_t bandLogCapacity(void);

#endif // ENABLE_BAND_LOG
#endif // _OPENGD77_BAND_LOG_H_
