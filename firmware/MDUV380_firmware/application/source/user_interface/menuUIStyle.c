/*
 * UI Style screen - Options -> Theme Options -> UI Style.
 *
 * Deliberately modelled on the theme screens next door, including their save
 * convention: Green previews, SK2 + Green writes to flash, Red discards. The
 * whole point of this screen is that it behaves like the colour editor the user
 * already knows, so it is worth matching even where a different design might be
 * marginally tidier.
 */
#include "functions/uiStyle.h"

#if defined(ENABLE_UI_STYLE)

#include "user_interface/uiGlobals.h"
#include "user_interface/menuSystem.h"
#include "user_interface/uiUtilities.h"
#include "user_interface/uiLocalisation.h"
#include "functions/settings.h"

enum
{
	UI_STYLE_ENTRY_SMETER_HEIGHT = 0,
	UI_STYLE_ENTRY_SMETER_TICKS,
	UI_STYLE_ENTRY_SMETER_ZONES,
	UI_STYLE_ENTRY_BATT_ICON,
	UI_STYLE_ENTRY_TX_HEADER,
	UI_STYLE_ENTRY_GPS_ICON,
#if defined(ENABLE_WATERFALL)
	UI_STYLE_ENTRY_WF_CONTRAST,
#endif
	NUM_UI_STYLE_ENTRIES
};

// Every entry past the first is a simple flag toggle, so they share one table
// rather than a case each.
static const uint8_t entryFlags[NUM_UI_STYLE_ENTRIES] =
{
	0,                              /* SMETER_HEIGHT is a value, not a flag */
	UI_STYLE_FLAG_SMETER_TICKS,
	UI_STYLE_FLAG_SMETER_ZONES,
	UI_STYLE_FLAG_BATT_ICON,
	UI_STYLE_FLAG_TX_HEADER,
	UI_STYLE_FLAG_GPS_ICON,
#if defined(ENABLE_WATERFALL)
	0                               /* WF_CONTRAST is a value, not a flag */
#endif
};

// `const char * const`, not `const char *`: the latter makes the *pointees*
// const but leaves the array itself writable, so it lands in .data and costs
// RAM - which this target has about fifty bytes of.
static const char * const entryNames[NUM_UI_STYLE_ENTRIES] =
{
	"S-meter H",
	"S-mtr ticks",
	"S-mtr zones",
	"Batt icon",
	"TX header",
	"GPS icon",
#if defined(ENABLE_WATERFALL)
	"WF gamma"
#endif
};

static uiStyle_t workingCopy;   // edits land here; only a save copies them out
static void updateScreen(bool isFirstRun);
static void handleEvent(uiEvent_t *ev);

menuStatus_t menuUIStyle(uiEvent_t *ev, bool isFirstRun)
{
	if (isFirstRun)
	{
		workingCopy = uiStyle;
		menuDataGlobal.numItems = NUM_UI_STYLE_ENTRIES;
		menuDataGlobal.currentItemIndex = 0;
		updateScreen(true);
		return (MENU_STATUS_LIST_TYPE | MENU_STATUS_SUCCESS);
	}

	if (ev->hasEvent)
	{
		handleEvent(ev);
	}

	return MENU_STATUS_SUCCESS;
}

static void valueText(int entry, char *buf, size_t len)
{
	if (entry == UI_STYLE_ENTRY_SMETER_HEIGHT)
	{
		snprintf(buf, len, "%u px", workingCopy.smeterHeight);
		return;
	}

#if defined(ENABLE_WATERFALL)
	if (entry == UI_STYLE_ENTRY_WF_CONTRAST)
	{
		static const char * const names[] = { "?", "Linear", "Square", "Cube" };
		uint8_t c = workingCopy.wfContrast;

		snprintf(buf, len, "%s", names[((c >= UI_STYLE_WF_LINEAR) && (c <= UI_STYLE_WF_CUBE))
				? c : UI_STYLE_WF_SQUARE]);
		return;
	}
#endif

	if ((entry > 0) && (entry < NUM_UI_STYLE_ENTRIES))
	{
		snprintf(buf, len, "%s", ((workingCopy.flags & entryFlags[entry])
				? currentLanguage->on : currentLanguage->off));
		return;
	}

	buf[0] = 0;
}

static void updateScreen(bool isFirstRun)
{
	char buf[SCREEN_LINE_BUFFER_SIZE];
	char val[SCREEN_LINE_BUFFER_SIZE];

	displayClearBuf();
	menuDisplayTitle("UI Style");

	for (int i = MENU_START_ITERATION_VALUE; i <= MENU_END_ITERATION_VALUE; i++)
	{
		int mNum = menuGetMenuOffset(NUM_UI_STYLE_ENTRIES, i);

		if ((mNum == MENU_OFFSET_BEFORE_FIRST_ENTRY) || (mNum == MENU_OFFSET_AFTER_LAST_ENTRY))
		{
			continue;
		}

		valueText(mNum, val, SCREEN_LINE_BUFFER_SIZE);
		snprintf(buf, SCREEN_LINE_BUFFER_SIZE, "%s:%s", entryNames[mNum], val);
		menuDisplayEntry(i, mNum, buf, 0, THEME_ITEM_FG_MENU_ITEM,
				THEME_ITEM_FG_OPTIONS_VALUE, THEME_ITEM_BG);
	}

	displayRender();
}

static void adjust(int entry, bool increase)
{
#if defined(ENABLE_WATERFALL)
	if (entry == UI_STYLE_ENTRY_WF_CONTRAST)
	{
		uint8_t c = uiStyleWaterfallContrastOf(workingCopy.wfContrast);

		if (increase)
		{
			if (c < UI_STYLE_WF_CUBE) { c++; }
		}
		else if (c > UI_STYLE_WF_LINEAR)
		{
			c--;
		}

		workingCopy.wfContrast = c;
		return;
	}
#endif

	if (entry == UI_STYLE_ENTRY_SMETER_HEIGHT)
	{
		if (increase)
		{
			if (workingCopy.smeterHeight < UI_STYLE_SMETER_H_MAX)
			{
				workingCopy.smeterHeight += 2;
			}
		}
		else if (workingCopy.smeterHeight > UI_STYLE_SMETER_H_MIN)
		{
			workingCopy.smeterHeight -= 2;
		}
		return;
	}

	if ((entry > 0) && (entry < NUM_UI_STYLE_ENTRIES))
	{
		workingCopy.flags ^= entryFlags[entry];
	}
}

static void handleEvent(uiEvent_t *ev)
{
	if (ev->events & KEY_EVENT)
	{
		if (KEYCHECK_PRESS(ev->keys, KEY_DOWN))
		{
			menuSystemMenuIncrement(&menuDataGlobal.currentItemIndex, NUM_UI_STYLE_ENTRIES);
			updateScreen(false);
			return;
		}
		else if (KEYCHECK_PRESS(ev->keys, KEY_UP))
		{
			menuSystemMenuDecrement(&menuDataGlobal.currentItemIndex, NUM_UI_STYLE_ENTRIES);
			updateScreen(false);
			return;
		}
		else if (KEYCHECK_PRESS(ev->keys, KEY_RIGHT))
		{
			adjust(menuDataGlobal.currentItemIndex, true);
			uiStyle = workingCopy;   // live preview, same as the colour editor
			updateScreen(false);
			return;
		}
		else if (KEYCHECK_PRESS(ev->keys, KEY_LEFT))
		{
			adjust(menuDataGlobal.currentItemIndex, false);
			uiStyle = workingCopy;
			updateScreen(false);
			return;
		}
		else if (KEYCHECK_SHORTUP(ev->keys, KEY_GREEN))
		{
			uiStyle = workingCopy;

			// SK2 + Green makes it permanent, exactly as in Theme Options.
			if (BUTTONCHECK_DOWN(ev, BUTTON_SK2))
			{
				uiStyleSaveToFlash();
			}

			menuSystemPopPreviousMenu();
			return;
		}
		else if (KEYCHECK_SHORTUP(ev->keys, KEY_RED))
		{
			uiStyleInit();   // drop the preview, go back to what is stored
			menuSystemPopPreviousMenu();
			return;
		}
	}
}

#endif // ENABLE_UI_STYLE
