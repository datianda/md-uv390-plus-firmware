/*
 * 中文点阵字库：住在外部 16MB SPI flash 的 0x800000（芯片中点）。
 *
 * 为什么不放内部 flash：一级+二级 6768 字 12x12 要 158 KB，而内部 flash 能给普通
 * const 用的只有 codec 之前那段填充 —— 实测 95,476 字节，放不下。外部 flash 的
 * 0x223000-0xE00000 有 11.86 MB 连续空白（实机整片备份扫出来的），随便用。
 * 地址选 8 MB 是为了上下都离得远：往下离已用区顶端 5.86 MB，往上离频段日志
 * (0xE00000) 5.00 MB。分区图见项目根目录 FLASH-MAP.md。
 *
 * 为什么要有个头：字库是用户自己生成后单独烧进去的，固件必须能分辨"烧了没有"。
 * BA7IQE 的实现没有头，字库没烧就满屏乱码。有 magic 就能老实退回英文。
 * 几何参数（字宽/字高/每字字节数）也从头里读，所以**换字号不用重编固件**。
 *
 * RAM 开销：一个 12 字节的静态结构。字形直接解进调用方栈上已有的
 * uncompressChar[64]（12x12 = 24 字节，13x13 = 26 字节，都塞得下），
 * 所以**主 RAM 零新增** —— 这点很重要，主 RAM 只剩 64 字节。
 */
#ifndef _OPENGD77_CJK_FONT_H_
#define _OPENGD77_CJK_FONT_H_

#include <stdint.h>
#include <stdbool.h>

#if defined(ENABLE_CJK)

#define CJK_FONT_FLASH_BASE   (8 * 1024 * 1024)   /* 0x800000 */
#define CJK_FONT_MAGIC        0x464B4A43U         /* 'CJKF' 小端 */
#define CJK_FONT_MAX_BYTES    64                  /* 不能超过 uncompressChar[] */

/* GB2312 汉字区：首字节 0xB0-0xF7，次字节 0xA1-0xFE，共 72*94 = 6768 槽。
 * 0xD7FA-0xD7FE 那 5 个码位 GB2312 没定义，留空槽不压缩 —— 省 5 个字不值得
 * 多一个分支和一处差一错。 */
#define CJK_LEAD_LO   0xB0
#define CJK_LEAD_HI   0xF7
#define CJK_TRAIL_LO  0xA1
#define CJK_TRAIL_HI  0xFE
#define CJK_COLS      (CJK_TRAIL_HI - CJK_TRAIL_LO + 1)

void cjkFontInit(void);          /* 开机读一次头并校验 magic */
bool cjkFontIsReady(void);
uint8_t cjkFontWidth(void);
uint8_t cjkFontHeight(void);
uint8_t cjkFontBytesPerGlyph(void);

/* 这两个字节是不是一个汉字。不校验字库在不在 —— 调用方先问 cjkFontIsReady()。 */
static inline bool cjkIsLeadByte(uint8_t b0, uint8_t b1)
{
	return ((b0 >= CJK_LEAD_LO) && (b0 <= CJK_LEAD_HI) &&
			(b1 >= CJK_TRAIL_LO) && (b1 <= CJK_TRAIL_HI));
}

/*
 * 取一个字形到 dest，dest 至少要有 cjkFontBytesPerGlyph() 字节。
 * 排布**直接就是渲染器要的样子**，读出来不用任何解包：
 *     byte = dest[x + (y / 8) * width]      位 = (byte >> (y % 8)) & 1
 * 失败返回 false（字库没烧、码位越界、SPI 读失败），调用方应退回 ASCII。
 */
bool cjkFontGetGlyph(uint8_t b0, uint8_t b1, uint8_t *dest);

#endif /* ENABLE_CJK */

#endif /* _OPENGD77_CJK_FONT_H_ */
