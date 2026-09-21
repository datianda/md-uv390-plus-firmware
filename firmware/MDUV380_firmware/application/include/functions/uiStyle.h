/*
 * UI style options.
 *
 * OpenGD77's theme system already lets the user recolour everything, but the
 * *shape* of the screen is fixed: the S-meter is 4 pixels tall on a 160x128
 * colour panel, its S-unit graduations exist in the source but sit behind an
 * `#if 0`, and the header is 15 text draws against a handful of rectangles.
 * This block makes those choices settable rather than compiled in.
 *
 * Stored as its own custom-data block rather than appended to THEME_DAY /
 * THEME_NIGHT: those two are read back as a fixed-length uint16_t array, so
 * growing them risks invalidating colours a user has already saved. A block of
 * our own is absent-by-default on every existing radio, and absent simply means
 * "use the defaults" - no migration, no version bump, nothing to reset.
 *
 * Unlike the colours, these are NOT per day/night: a bar is the same height at
 * night, only its colour changes.
 */
#ifndef _OPENGD77_UI_STYLE_H_
#define _OPENGD77_UI_STYLE_H_

#include <stdint.h>
#include <stdbool.h>

#if defined(ENABLE_UI_STYLE)

#define UI_STYLE_MAGIC   0x55   /* 'U' - anything else means "not written yet" */

/* Bit flags in uiStyle_t.flags */
#define UI_STYLE_FLAG_SMETER_TICKS   (1 << 0)   /* S1/S3/S5/S7/S9 graduations */
#define UI_STYLE_FLAG_SMETER_ZONES   (1 << 1)   /* colour by strength, not one flat bar */
#define UI_STYLE_FLAG_BATT_ICON      (1 << 2)   /* battery glyph instead of "NN%" */
#define UI_STYLE_FLAG_TX_HEADER      (1 << 3)   /* tint the whole header while transmitting */
#define UI_STYLE_FLAG_GPS_ICON       (1 << 4)   /* fix indicator in the header */

typedef struct __attribute__((packed))
{
	uint8_t magic;          /* UI_STYLE_MAGIC once written                       */
	uint8_t smeterHeight;   /* pixels; clamped to UI_STYLE_SMETER_H_MIN..MAX     */
	uint8_t flags;          /* UI_STYLE_FLAG_*                                   */
	uint8_t wfContrast;     /* waterfall gamma; 0 = never set, see below         */
} uiStyle_t;

/* Waterfall gamma: how hard the noise floor is pushed down before the colour ramp.
 *
 * There is no single right answer, which is why it is a setting. Measured on 70 cm
 * here, band noise sits at level 19 of 63 and the strongest real carrier reached about
 * 43. Squaring puts the noise at 7 and the carrier at 29 - a calm floor, but the top
 * half of the ramp never gets used. Linear uses the whole ramp and lights the noise up
 * with it; cube buries the noise almost completely and dims weak signals with it.
 * Which is right depends on the band and the day.
 *
 * ZERO MEANS SQUARE, not linear: every style block saved before this option existed has
 * a zero in this byte, and the behaviour then was the square law. Redefining zero would
 * silently change the display for anyone who had already saved one.
 */
#define UI_STYLE_WF_LINEAR  1
#define UI_STYLE_WF_SQUARE  2
#define UI_STYLE_WF_CUBE    3

#define UI_STYLE_SMETER_H_MIN      4
#define UI_STYLE_SMETER_H_MAX     10
#define UI_STYLE_SMETER_H_DEFAULT  4   /* stock look until the user changes it */

extern uiStyle_t uiStyle;

void uiStyleInit(void);           /* load from flash, or install the defaults */
bool uiStyleSaveToFlash(void);
void uiStyleResetToDefaults(void);

static inline bool uiStyleFlag(uint8_t flag)
{
	return ((uiStyle.flags & flag) != 0);
}

/* Shared by the live setting and the menu's working copy, so both read a stored zero
 * the same way instead of each having its own idea of the default. */
static inline uint8_t uiStyleWaterfallContrastOf(uint8_t stored)
{
	return (((stored >= UI_STYLE_WF_LINEAR) && (stored <= UI_STYLE_WF_CUBE))
			? stored : UI_STYLE_WF_SQUARE);
}

static inline uint8_t uiStyleWaterfallContrast(void)
{
	return uiStyleWaterfallContrastOf(uiStyle.wfContrast);
}

#endif // ENABLE_UI_STYLE
#endif // _OPENGD77_UI_STYLE_H_
