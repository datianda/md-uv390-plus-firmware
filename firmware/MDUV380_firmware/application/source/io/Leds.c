/*
 * Copyright (C) 2019      Kai Ludwig, DG4KLU
 * Copyright (C) 2019-2025 Roger Clark, VK3KYY / G4KYF
 *                         Daniel Caujolle-Bert, F1RMB
 *
 *
 * Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions
 * are met:
 *
 * 1. Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.
 *
 * 2. Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer
 *    in the documentation and/or other materials provided with the distribution.
 *
 * 3. Neither the name of the copyright holder nor the names of its contributors may be used to endorse or promote products derived
 *    from this software without specific prior written permission.
 *
 * 4. Use of this source code or binary releases for commercial purposes is strictly forbidden. This includes, without limitation,
 *    incorporation in a commercial product or incorporation into a product or project which allows commercial use.
 *
 * THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
 * LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
 * HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
 * LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON
 * ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE
 * USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
 *
 */
#include "interfaces/gpio.h"
#include "io/LEDs.h"
#include "functions/trx.h"
#include "functions/rxPowerSaving.h"
#include "hardware/HR-C6000.h"
#include "hardware/radioHardwareInterface.h"
#include "user_interface/menuSystem.h"
#include "functions/ticks.h"

#if ! defined(PLATFORM_GD77S)
uint8_t LEDsState[NUM_LEDS] = { 0, 0 };
#endif


void LEDsInit(void)
{
#if defined(PLATFORM_MD9600) || defined(PLATFORM_GD77) || defined(PLATFORM_GD77S) || defined(PLATFORM_DM1801) || defined(PLATFORM_DM1801A) || defined(PLATFORM_RD5R)
	gpioInitLEDs();
#endif

	LedWrite(LED_GREEN, 0);
	LedWrite(LED_RED, 0);

#if defined(PLATFORM_RD5R)
	GPIO_PinWrite(GPIO_Torch, Pin_Torch, 0);
#endif
}

void LedWrite(LEDs_t theLED, uint8_t output)
{
#if ! defined(PLATFORM_GD77S)
	LEDsState[theLED] = output;

	if (settingsIsOptionBitSet(BIT_ALL_LEDS_DISABLED) == 0)
#endif
	{
		LedWriteDirect(theLED, output);
	}
}

/*
 * Who owns the green LED.
 *
 * Before this, nobody did. There are 29 LedWrite(LED_GREEN, ...) call sites spread
 * over ten modules, and every one of them is an EDGE write: "my state machine just
 * changed, so poke the LED on the way past". Nothing ever re-derived the indicator
 * from the state it is supposed to represent, so a single transition that got
 * skipped -- by an early return, by a path nobody expected, by two writers racing --
 * left the LED wrong until some unrelated transition happened to correct it.
 *
 * That is not a theory. trxCheckAnalogSquelch() closes the squelch with
 *
 *     if (currentRadioDevice->analogSignalReceived || LedRead(LED_GREEN))
 *
 * -- reading the LED back as if it were the state variable, because that state has
 * no home. And the CTCSS-hold branch just above it clears analogSignalReceived
 * without touching the LED at all.
 *
 * Eco turns any such slip into a permanent one. With the receiver powered down,
 * trxReadRSSIAndNoise() stops sampling, so the squelch test can never again reach
 * its LED-off branch. Green then stays lit while the receiver is switched off --
 * the one thing this indicator must never claim.
 *
 * So the fix is not to chase the 29 writers; there is no way to prove that set is
 * complete. It is to add the one that was missing: a level-driven owner that
 * recomputes the indicator from current state every tick. The edge writes are left
 * exactly as they are. They now only lower latency, and anything they get wrong is
 * corrected within one tick instead of never.
 */
#if defined(ENABLE_DIAG)
/*
 * The trace ring.
 *
 * In CCM because main RAM has 64 bytes spare and this needs 160; CCM had 236. Startup
 * does not zero .ccmram, so squelchTraceInit() has to, exactly like the AES state.
 *
 * Only transitions are stored. The fault being chased is "green stays lit with nothing
 * on frequency", which is one transition in and then silence, so a change-triggered ring
 * holds the entry even if the radio then sits in the fault for minutes.
 */
static __attribute__((section(".ccmram"))) squelchTraceEvent_t traceRing[SQUELCH_TRACE_ENTRIES];
static __attribute__((section(".ccmram"))) uint8_t traceNext;
static __attribute__((section(".ccmram"))) uint8_t traceWrapped;
static __attribute__((section(".ccmram"))) uint8_t traceLastFlags;
static __attribute__((section(".ccmram"))) uint8_t tracePrimed;

void squelchTraceInit(void)
{
	for (uint32_t i = 0; i < SQUELCH_TRACE_ENTRIES; i++)
	{
		traceRing[i].ms = 0;
		traceRing[i].noise = 0;
		traceRing[i].rssi = 0;
		traceRing[i].flags = 0;
		traceRing[i].modeSlot = 0;
	}
	traceNext = 0;
	traceWrapped = 0;
	traceLastFlags = 0;
	tracePrimed = 0;
}

uint8_t squelchTraceCount(void)
{
	return (traceWrapped ? SQUELCH_TRACE_ENTRIES : traceNext);
}

uint8_t squelchTraceWrapped(void)
{
	return traceWrapped;
}

const squelchTraceEvent_t *squelchTraceAt(uint8_t i)
{
	return &traceRing[i % SQUELCH_TRACE_ENTRIES];
}

static void squelchTraceSample(uint8_t want)
{
	uint8_t flags = (uint8_t)((LedRead(LED_GREEN) ? 0x01 : 0) |
			(want ? 0x02 : 0) |
			(rxPowerSavingIsRxOn() ? 0x04 : 0) |
			(currentRadioDevice->analogSignalReceived ? 0x08 : 0) |
			(currentRadioDevice->digitalSignalReceived ? 0x10 : 0) |
			((trxIsTransmitting || trxTransmissionEnabled) ? 0x20 : 0));

	if (tracePrimed && (flags == traceLastFlags))
	{
		return;
	}
	traceLastFlags = flags;
	tracePrimed = 1;

	traceRing[traceNext].ms = ticksGetMillis();
	traceRing[traceNext].noise = currentRadioDevice->trxRxNoise;
	traceRing[traceNext].rssi = currentRadioDevice->trxRxSignal;
	traceRing[traceNext].flags = flags;
	traceRing[traceNext].modeSlot = (uint8_t)((currentRadioDevice->currentMode & 0x0F) |
			((slotState & 0x0F) << 4));

	traceNext++;
	if (traceNext >= SQUELCH_TRACE_ENTRIES)
	{
		traceNext = 0;
		traceWrapped = 1;
	}
}
#endif

bool ledsGreenShouldBeOn(void)
{
	// Transmit belongs to the red LED.
	if (trxIsTransmitting || trxTransmissionEnabled)
	{
		return false;
	}

	// Eco has powered the receiver down, so nothing can be arriving.
	if (rxPowerSavingIsRxOn() == false)
	{
		return false;
	}

	switch (currentRadioDevice->currentMode)
	{
		case RADIO_MODE_ANALOG:
			return currentRadioDevice->analogSignalReceived;

		case RADIO_MODE_DIGITAL:
			// Two independent views of "a call is up": digitalSignalReceived is the
			// RSSI one (trx.c), slotState is the frame one (HR-C6000.c). Either can
			// be the live one, so the indicator is the union.
			return (currentRadioDevice->digitalSignalReceived ||
					(slotState == DMR_STATE_RX_1) || (slotState == DMR_STATE_RX_2));

		default:
			return false;   // RADIO_MODE_NONE: CPS screen and friends
	}
}

static uint32_t greenCorrections = 0;

uint32_t ledsGreenCorrectionCount(void)
{
	return greenCorrections;
}

void ledsTick(void)
{
	// Screens that drive the LEDs deliberately keep ownership while they are up.
	switch (menuSystemGetCurrentMenuNumber())
	{
		case UI_CPS:
		case UI_HOTSPOT_MODE:
		case UI_TX_SCREEN:
			return;

		default:
			break;
	}

	uint8_t want = (ledsGreenShouldBeOn() ? 1 : 0);

#if defined(ENABLE_DIAG)
	squelchTraceSample(want);
#endif

	if (LedRead(LED_GREEN) != want)
	{
		// Counted, not just corrected: this number is the evidence for whether the
		// edge writers actually get it wrong, and how often.
		greenCorrections++;
		LedWrite(LED_GREEN, want);
	}
}

uint8_t LedRead(LEDs_t theLED)
{
#if defined(PLATFORM_GD77S)
	return GPIO_PinRead(((theLED == LED_GREEN) ? GPIO_LEDgreen : GPIO_LEDred), ((theLED == LED_GREEN) ? Pin_LEDgreen : Pin_LEDred));
#else
	return LEDsState[theLED];
#endif
}

void LedWriteDirect(LEDs_t theLED, uint8_t output)
{
#if defined(PLATFORM_GD77S)
	GPIO_PinWrite(((theLED == LED_GREEN) ? GPIO_LEDgreen : GPIO_LEDred), ((theLED == LED_GREEN) ? Pin_LEDgreen : Pin_LEDred), output);
#else
	LEDsState[theLED] = output;

#if ! defined(PLATFORM_MD9600)
	if (theLED == LED_GREEN)
	{
#if defined(PLATFORM_GD77) || defined(PLATFORM_GD77S) || defined(PLATFORM_DM1801) || defined(PLATFORM_DM1801A) || defined(PLATFORM_RD5R)
		GPIO_PinWrite(GPIO_LEDgreen, Pin_LEDgreen, output);
#else
		HAL_GPIO_WritePin(LED_GREEN_GPIO_Port, LED_GREEN_Pin, output);
#endif
	}
	else
	{
#if defined(PLATFORM_GD77) || defined(PLATFORM_GD77S) || defined(PLATFORM_DM1801) || defined(PLATFORM_DM1801A) || defined(PLATFORM_RD5R)
		GPIO_PinWrite(GPIO_LEDred, Pin_LEDred, output);
#else
		HAL_GPIO_WritePin(LED_RED_GPIO_Port, LED_RED_Pin, output);
#endif
	}
#endif // ! MD9600
#endif // ! GD77S
}

#if defined(PLATFORM_RD5R)
// Baofeng DM-5R torch LED
static bool torchState = false;

void torchToggle(void)
{
	torchState = !torchState;
	GPIO_PinWrite(GPIO_Torch, Pin_Torch, torchState);
}
#endif
