/*
 * 中文点阵字库的读取侧。生成与烧写在 tools/cjkfont.py，格式见 FLASH-MAP.md。
 */
#include "functions/cjkFont.h"

#if defined(ENABLE_CJK)

#include "hardware/SPI_Flash.h"

/* 头在区起点，32 字节，小端。这里只取用得上的字段。 */
typedef struct __attribute__((packed))
{
	uint32_t magic;
	uint8_t  version;
	uint8_t  encoding;
	uint8_t  width;
	uint8_t  height;
	uint8_t  bytesPerGlyph;
	uint8_t  reserved;
	uint16_t glyphCount;
	uint32_t dataOffset;
	uint32_t dataLength;
	uint32_t crc32;
	uint32_t epoch;
	uint32_t reserved2;
} cjkFontHeader_t;

/* 只留后面真要用的几项，省 RAM。主 RAM 只剩 64 字节，能省则省。 */
static struct
{
	uint32_t dataBase;       /* 绝对地址：CJK_FONT_FLASH_BASE + dataOffset */
	uint16_t glyphCount;
	uint8_t  width;
	uint8_t  height;
	uint8_t  bytesPerGlyph;
	bool     ready;
} cjk;

void cjkFontInit(void)
{
	cjkFontHeader_t h;

	cjk.ready = false;

	if (SPI_Flash_read(CJK_FONT_FLASH_BASE, (uint8_t *)&h, sizeof(h)) == false)
	{
		return;
	}

	if (h.magic != CJK_FONT_MAGIC)
	{
		return;   // 没烧字库。安静地退回英文，不要画乱码。
	}

	/* 字形要解进调用方栈上的 uncompressChar[64]，超了就当没字库 —— 宁可不显示，
	 * 也不能写爆别人的栈。 */
	if ((h.bytesPerGlyph == 0) || (h.bytesPerGlyph > CJK_FONT_MAX_BYTES) ||
			(h.width == 0) || (h.height == 0) || (h.glyphCount == 0) ||
			(h.bytesPerGlyph != (h.width * ((h.height + 7) / 8))))
	{
		return;
	}

	cjk.dataBase      = CJK_FONT_FLASH_BASE + h.dataOffset;
	cjk.glyphCount    = h.glyphCount;
	cjk.width         = h.width;
	cjk.height        = h.height;
	cjk.bytesPerGlyph = h.bytesPerGlyph;
	cjk.ready         = true;
}

bool cjkFontIsReady(void)
{
	return cjk.ready;
}

uint8_t cjkFontWidth(void)
{
	return cjk.width;
}

uint8_t cjkFontHeight(void)
{
	return cjk.height;
}

uint8_t cjkFontBytesPerGlyph(void)
{
	return cjk.bytesPerGlyph;
}

bool cjkFontGetGlyph(uint8_t b0, uint8_t b1, uint8_t *dest)
{
	if ((cjk.ready == false) || (cjkIsLeadByte(b0, b1) == false))
	{
		return false;
	}

	uint32_t slot = ((uint32_t)(b0 - CJK_LEAD_LO) * CJK_COLS) + (b1 - CJK_TRAIL_LO);

	if (slot >= cjk.glyphCount)
	{
		return false;
	}

	/* 一次 SPI 读，读出来就是渲染器要的列优先排布，不用解包。
	 * （BA7IQE 按 16.5 字节压存，省 25% 空间，代价是浮点乘、17 字节读、
	 *   还要按奇偶相位拆半字节 —— 我们有 11.86 MB 空白，不值。） */
	return SPI_Flash_read(cjk.dataBase + (slot * cjk.bytesPerGlyph), dest,
			cjk.bytesPerGlyph);
}

#endif /* ENABLE_CJK */
