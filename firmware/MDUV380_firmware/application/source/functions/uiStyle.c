/* UI style options - see uiStyle.h for why this is its own custom-data block. */
#include "functions/uiStyle.h"

#if defined(ENABLE_UI_STYLE)

#include "functions/codeplug.h"

// The defaults reproduce the stock look exactly, so a radio that has never
// visited the UI Style screen looks the same as it did before this existed.
uiStyle_t uiStyle =
{
	.magic        = UI_STYLE_MAGIC,
	.smeterHeight = UI_STYLE_SMETER_H_DEFAULT,
	.flags        = 0,
	.wfContrast   = UI_STYLE_WF_SQUARE
};

void uiStyleResetToDefaults(void)
{
	uiStyle.magic        = UI_STYLE_MAGIC;
	uiStyle.smeterHeight = UI_STYLE_SMETER_H_DEFAULT;
	uiStyle.flags        = 0;
	uiStyle.wfContrast   = UI_STYLE_WF_SQUARE;
}

void uiStyleInit(void)
{
	uiStyle_t tmp;

	if (codeplugGetOpenGD77CustomDataBounded(CODEPLUG_CUSTOM_DATA_TYPE_UI_STYLE,
			(uint8_t *)&tmp, sizeof(uiStyle_t)) && (tmp.magic == UI_STYLE_MAGIC))
	{
		// Clamp rather than trust: the block lives in flash the CPS can also
		// write, and an out-of-range height would draw outside the header.
		if (tmp.smeterHeight < UI_STYLE_SMETER_H_MIN)
		{
			tmp.smeterHeight = UI_STYLE_SMETER_H_MIN;
		}
		else if (tmp.smeterHeight > UI_STYLE_SMETER_H_MAX)
		{
			tmp.smeterHeight = UI_STYLE_SMETER_H_MAX;
		}

		uiStyle = tmp;
		return;
	}

	uiStyleResetToDefaults();
}

bool uiStyleSaveToFlash(void)
{
	uiStyle.magic = UI_STYLE_MAGIC;
	return codeplugSetOpenGD77CustomData(CODEPLUG_CUSTOM_DATA_TYPE_UI_STYLE,
			(uint8_t *)&uiStyle, sizeof(uiStyle_t));
}

#endif // ENABLE_UI_STYLE
