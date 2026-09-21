# 第三方组件、商标与法律声明

这份文件随源码和二进制一起分发。请连同 [`LICENSE.txt`](LICENSE.txt) 一并阅读。

---

## 1. 上游与授权

本仓库是 **OpenGD77** 的一个衍生作品。

| 组件 | 来源 | 授权 |
|---|---|---|
| OpenGD77 固件 | 官方源码发布 **R20260131**，目标 `MDUV380_10W_PLUS_FW` | BSD 三条款 **+ 禁止商业使用**，见 `LICENSE.txt` |
| DMRA AES-256 实现 | fork [`dondch/OpenGD77-AES256`](https://github.com/dondch/OpenGD77-AES256)，commit `2ce799d` | 同上 |
| 本仓库的改动 | 见 [`docs/ROADMAP.md`](docs/ROADMAP.md) | 同上 |
| STM32 HAL / CMSIS | STMicroelectronics，随 OpenGD77 源码分发 | ST 的 BSD-3-Clause |
| FreeRTOS | 随 OpenGD77 源码分发 | MIT |
| `codec_cleaner` | OpenGD77 官方工具，二进制原样带入 | 同 OpenGD77 |

`LICENSE.txt` 的版权声明、四条条件与免责声明**原样保留**，源码与二进制分发都随附 ——
这是该授权条款 1 和条款 2 的要求。

### 条款 4：禁止商业使用

> *Use of this source code or binary releases for commercial purposes is strictly forbidden.
> This includes, without limitation, incorporation in a commercial product or incorporation
> into a product or project which allows commercial use.*

**这条对本仓库同样生效。** 因此本仓库不能改挂 MIT / Apache-2.0 之类允许商业使用的授权 ——
那会与上游条款冲突。你可以自用、研究、修改、再分发，但**不能用于任何商业目的**。

### 条款 3：无从属声明

> *Neither the name of the copyright holder nor the names of its contributors may be used to
> endorse or promote products derived from this software without specific prior written permission.*

**本项目与 OpenGD77 项目及其作者、贡献者没有从属、赞助或背书关系。**
**本项目与深圳市特易通电子有限公司（TYT / TYT Electronics）也没有任何从属、授权或背书关系。**
"TYT"、"MD-UV380"、"MD-UV390"、"MD-9600" 是其各自所有者的商标，此处仅用于说明兼容机型。

遇到问题请到本仓库提 issue，**不要去 OpenGD77 的论坛或 issue 区问** —— 这不是他们的构建。

---

## 2. AMBE 语音编解码器：本仓库不含、不分发

MD-UV390 的 DMR 语音需要 AMBE 编解码器。它是**第三方专有代码**，OpenGD77 从来不分发它，
本仓库同样不分发。

- 发布的 `.bin` 里，编解码器所在的那 **297904 字节全是 `0xFF`**（空白占位）。可以自己验：
  从文件偏移 `0x6937C` 起数 `0x48BB0` 字节。
- 刷机时由烧录器从**你自己那份 TYT MD-9600 固件**里取出并拼接进去。
  这份 donor 是 TYT 的版权作品，**你得自己拥有，本仓库不提供、也不会提供**。

这跟 OpenGD77 官方的做法完全一致。

---

## 3. ⚠️ AES-256 加密语音：法律警告

本固件编译时开启了 `ENABLE_AES`，带 DMRA AES-256 加密语音（继承自上游 fork）。

- **在绝大多数国家和地区，业余无线电频段上禁止使用加密通信**，中国也在其列。
  加密语音只在你**持有相应许可的商用 / 专网频段**上才可能合法。
- 各地对加密软件的分发本身也可能另有规定，**使用与分发的合规责任在你自己**。
- **本项目作者没有在任何频段上实测过这个功能的收发。** 只确认了菜单能打开。
  见 README 的「已知限制」。

如果你不需要这个功能、或所在地不允许，**去掉 `ENABLE_AES=1` 自行编译即可** ——
其余全部功能都不依赖它，编译命令见 README。

---

## 4. ⚠️ 发射相关

- **发射需持有效业余无线电执照，并使用本人呼号。** 没有执照就只接收、只翻菜单。
- 频段、功率、占用带宽的合规**由操作者自己负责**。本固件不替你做判断，
  也没有内置发射限制 —— 它是给测试与研究用的。
- 硬件本身的频率范围是 AT1846S 芯片的物理限制（约 127–178 / 380–564 MHz），软件放不开。

---

## 5. 免责

见 `LICENSE.txt` 的免责条款：**本软件按「原样」提供，不含任何明示或默示担保。**
刷固件有让电台不可用的风险；**刷之前先按 README 把 16 MB SPI flash 备份好**，
里面的出厂校准数据每台唯一、丢了补不回来。
