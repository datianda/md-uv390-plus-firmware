# 代码审计（2026-09-22）

独立分支前的一次体检。**只写量出来的，不写感觉。**
基线：`ENABLE_CJK=1 LANGUAGE_BUILD_CHINESE=1 ENABLE_KEY_INJECTION=1` + 常规开关，
主 RAM 剩 **1008 字节**，CCM 剩 3920 字节。

---

## A. RAM 是唯一真正的瓶颈，而最大那块有 67% 是浪费

`.bss` 前几名：

| 符号 | 字节 | 谁的 |
|---|---|---|
| `screenBufData` | 40,960 | 帧缓冲，160x128x2，动不了 |
| `ucHeap` | 20,480 | FreeRTOS 堆 |
| **`satelliteDataNative`** | **11,900** | **上游卫星功能** |
| `ambebuffer_encode` | 8,192 | codec，地址写死 |
| 4 个 USB 缓冲 | 8,192 | 2048 x 4 |

拆开 `satelliteDataNative`（25 颗 x 476 字节）：

| 组成 | 每颗 | 25 颗 | 占比 |
|---|---|---|---|
| 轨道根数 + 名字 + 频率 + 附加数据 | 156 | 3,900 | 33% |
| **`predictions`（15 个过境槽）** | **320** | **8,000** | **67%** |

**25 颗 x 15 个过境 = 375 个过境槽常驻内存。** UI 一次显示不了这么多。

| 每颗留几个过境 | 25 颗合计 | 省下 |
|---|---|---|
| 15（现状） | 11,900 | — |
| 8 | 8,400 | 3,500 |
| 4 | 6,400 | **5,500** |
| 2 | 5,400 | 6,500 |

降到 4 个能省 **5,500 字节 = 现有余量的 5.4 倍**。
这是上游的设计，不是我们加的。**会改行为**（每颗卫星能预测的过境数变少），
要不要改是产品决定，不是技术决定。

## B. 21 个编译开关，CI 只编 3 种组合

按引用点数排（少的在下面）：

    ENABLE_FAST_SCAN 61 | ENABLE_AES 29 | ENABLE_SPECTRUM 27 | ENABLE_DMR_DATA 27
    ENABLE_UI_STYLE 18 | ENABLE_WATERFALL 13 | ENABLE_CJK 13 | ENABLE_SAT_ALERT 9
    ENABLE_BAND_LOG 7 | DISABLE_SAT_ALARM 7 | ENABLE_THEME_PRESET 6
    LANGUAGE_BUILD_CHINESE 5 | ENABLE_SQUELCH_TRACE 5 | ENABLE_LED_OWNER 5
    ENABLE_KEY_INJECTION 5 | ENABLE_INFO_DENSITY 5 | ENABLE_SCAN_PROFILER 4
    ENABLE_DOPPLER_READOUT 2 | ENABLE_LED_DIAG 1 | ENABLE_ECO_WAKE_SETTLE 1
    ENABLE_ECO_SQUELCH_FIX 1

**判据：一个开关只有在"我们真的会关着它发一版"时才值得存在。**

按这个判据，下面这些不该是开关 —— 它们是**修好的 bug**，我们永远不会关着它发版：

| 开关 | 引用点 | 实质 |
|---|---|---|
| `ENABLE_ECO_SQUELCH_FIX` | 1 | Eco 关机时读静噪的修复 |
| `ENABLE_ECO_WAKE_SETTLE` | 1 | 补上事件唤醒缺的那次 settle |
| `ENABLE_LED_OWNER` | 5 | 绿灯没有所有者，是架构缺陷的补丁 |

留着它们只有一个代价：**组合爆炸**。21 个开关名义上 2^21 种组合，CI 只编 3 种，
也就是绝大多数组合从没编译过，更没跑过。

`DISABLE_SAT_ALARM` 是个**负向开关** —— 我们平时带着它编译，意思是"关掉这个功能"。
读代码的人每次都要在脑子里做一次否定。应该反过来叫 `ENABLE_SAT_ALARM`，默认关。

诊断类（`ENABLE_LED_DIAG`、`ENABLE_SQUELCH_TRACE`、`ENABLE_SCAN_PROFILER`、
`ENABLE_KEY_INJECTION`）该合并成**一个** `ENABLE_DIAG`：它们的使用场景完全一样，
都是"我要查问题所以编一版带仪器的"，从来不会只要其中一个。

收敛后大概剩 8 个：`AES / CJK / SPECTRUM / WATERFALL / FAST_SCAN / DMR_DATA /
DIAG / SAT_ALARM`（外加语言）。

## C. 一个真正的死标志（上游的）

    usb_com.h:64        extern volatile bool usbIsResetting;
    clockManager.c:37   extern volatile bool usbIsResetting;   <- 重复声明
    usb_com.c:118       volatile bool usbIsResetting = false;  <- 唯一一次赋值
    clockManager.c:134  if (usbIsResetting && ...)             <- 永远进不去
    usb_com.c:2440      return usbIsResetting;                 <- 永远返回 false

全树**没有任何地方把它置 true**。所以 `clockManager.c:134` 那个分支是死的，
那个 getter 是个恒假函数。而且它被 extern 了两次（头文件一次、clockManager.c 里
又手写一次），后者一改头文件就会失配。

**这条对我们不是纯洁癖**：查绿灯常亮时我把它当成过嫌疑对象，花了时间才排除。
死代码的代价就是这个 —— 它会骗后来的人。

## D. 静噪常数散落三处

    trx.c:101-103          #define TRX_SQUELCH_MAX/HIST/INC   <- 在 .c 里，不是头文件
    tools/squelchtrace.py  SQ_MAX, SQ_HIST, SQ_INC = 70, 3, 3  <- 主机侧抄了一份
    tools/leddiag.py       又自己算了一遍门限

三份副本会漂。正确做法是固件侧**直接把算好的门限报出来**（`0x99` 本来就有回应包），
主机侧别自己算。

## E. 我们自己写的代码：0 警告

全部编译警告都来自上游文件（`aprs.c`、`codeplug.c`、`hotspot.c`、`menuAPRSOptions.c`、
`usb_com.c`）。其中几条**像是真 bug**，值得单独看：

    menuAPRSOptions.c:420  'strncat' specified bound 17 equals destination size
    menuAPRSOptions.c:443  同上
    usb_com.c:1779/1780    memcpy 丢掉了 volatile 限定

`strncat` 的 bound 等于目标大小是经典的差一错 —— `strncat` 的第三参数是
**还能再追加多少**，不是缓冲区总大小，写成总大小就可能多写一个结束符出界。

---

## 建议的优先级

| | 事项 | 收益 | 风险 |
|---|---|---|---|
| 1 | 卫星预测表 15 -> 4 | **RAM +5,500 字节** | 改行为，要拍板 |
| 2 | 开关 21 -> 8，bug 修复转无条件 | 组合爆炸消失，可读性 | 低，但要全组合回归 |
| 3 | 删 `usbIsResetting` 死分支 | 少骗一个后来人 | 无 |
| 4 | 静噪常数收进头文件 + 工具改成问电台 | 三份副本不会再漂 | 无 |
| 5 | 逐条看上游那几条警告 | 可能是真 bug | 无 |

## 关于独立分支

授权不会因为"不再跟上游"而改变：BSD-3 + 第 4 条非商业条款照样适用，
版权声明得留着。

建议**留一个上游基线 tag**。不跟不等于看不见 —— 将来上游修了个我们也中招的 bug，
能 diff 出来捞过来。成本几乎为零，少了它就真成孤岛了。


---

# 执行结果（2026-09-22）

## 已完成

### A. 卫星预测表 15 -> 5（可用 4 次过境）

`satelliteDataNative` **11,900 -> 6,900 字节，省 5,000**。
主 RAM 空闲 **1,008 -> 6,008 字节**，涨了 6 倍。

顺带修掉一个上游的差一错：填充循环写的是
`if (numPasses < (NUM_SATELLITE_PREDICTIONS - 1))`，于是在 `numPasses == N-1` 时回退一格，
**实际只填 N-2 个过境，最后一个槽 `passes[N-1]` 从头到尾没人碰** ——
15 个槽只给了 13 个过境，白扔一格。槽位少了以后这一格占比更难看（1/5），所以改成 `< N`：
`passes[0..N-2]` 是真过境，`passes[N-1]` 放"还有更多"的截断哨兵，一格不浪费。

### B. 开关 21 -> 15（功能开关）

- **三个 bug 修复转无条件**：`ENABLE_ECO_SQUELCH_FIX`、`ENABLE_ECO_WAKE_SETTLE`、
  `ENABLE_LED_OWNER`。它们不是可选功能，我们永远不会关着它们发版。
- **四个诊断开关并成 `ENABLE_DIAG`**：`KEY_INJECTION` / `LED_DIAG` / `SQUELCH_TRACE` /
  `SCAN_PROFILER`。使用场景完全一样 ——「编一版带仪器的去查问题」，从来不会只要其中一个。
- **`DISABLE_SAT_ALARM` 反转成 `ENABLE_SAT_ALARM`**。原来平时**带着它**编译、
  意思却是"关掉这个功能"，双重否定，每次读都要在脑子里翻译一遍。

**合并当场抓出一个从没被编译过的组合 bug**：扫描性能计数器的实现住在 `spectrum.c`，
旧开关的注释写着"依赖 ENABLE_SPECTRUM"，但**只是注释，没有任何东西强制它**。
四个开关各管各的时候，"开诊断不开频谱"这个组合根本没人编过。合成一个之后这个组合
变得很自然，第一次回归编译就炸了。现在 `SCANPROF_*` 宏要求两个开关同时在，
缺频谱就退化成空操作。

**这正是收敛的价值**：21 个开关名义上 2^21 种组合、CI 只编 3 种，
绝大多数组合从没编译过，bug 就藏在那里。

回归编译 6 种组合全过：

| 组合 | 主 RAM 空闲 |
|---|---|
| 裸机（stock） | 8,168 |
| 常规 | 6,184 |
| 常规 + 中文 | 6,176 |
| 常规 + 中文 + 诊断（无频谱） | 6,008 |
| 诊断 + 频谱（无中文） | 4,576 |
| 全开（含 AES / 卫星闹钟 / 频谱） | 3,432 |

### C. 死代码清除

`usbIsResetting` 全树只有一次赋值（`= false`），**从没被置 true**。清掉它连带：

- `clockManagerUsbRequired()` —— **定义了但全树无人调用**，函数体还守在那个恒假标志上。整个删掉。
- `USB_DeviceIsResetting()` —— 返回值恒假（作为判据是死的），但它**藏了个活的副作用**：
  USB 枚举完成就把时钟拉到全速。一个名字在问句、返回值没人真用、真正作用藏在副作用里的
  函数，还被放在 Eco 热路径 `||` 链的第一个 —— 从调用点完全看不出它在改时钟。
  改名 `usbEnsureFullClockIfConnected()`、返回 void、调用点独立成行。

  **这条不是洁癖**：查绿灯常亮时我把它当嫌疑对象排查过，白费了时间。死代码会骗后来的人。

## 过程中的事故：Makefile 被清空

折叠脚本里删 Makefile 开关段，我图省事用了一条正则，形如：

    \n? # 注释行 ， 然后 (#注释行)* ， 然后 ifeq/DEFS/endif

关键是中间那个 **`(#注释行)*`** —— 它对「零到任意多条注释行」做回溯匹配。
Makefile 是注释密集的，于是它一路向前吃，直到撞上目标 stanza 为止，
把中间所有内容连同注释一起吞掉。三个 FOLD 开关跑三次，整个文件就空了。

**能恢复是因为发行仓库里有 git 跟踪的副本**（`release/md-uv390-plus-firmware/firmware/
MDUV380_firmware/Makefile`，v20260921），构建规则一字未失，只需补回之后新增的开关。

教训两条：

1. **不要用贪婪正则改整个文件。** 结构化的编辑要么逐行走、要么精确匹配单块。
   源码那边的折叠器是认 `#if/#endif` 配平的逐行实现，一处没错；
   出事的恰恰是图省事那半截。
2. **订正**：我当时写"固件树没有版本控制"，不准确。`firmware/OpenGD77-AES256`
   本来就是个 git 仓库 —— 但**只有一个提交，就是上游基线**，我们两周的工作
   （34 个改动 + 9 个新文件）全是未提交的工作区改动。所以 `git checkout Makefile`
   只会还原成上游版、丢掉我们所有开关；用发行仓库副本恢复反而是对的选择。
   真正的问题不是"没有 git"，是**从来没提交过**。

   已处理（2026-09-22）：
   - 基线打上 `upstream-baseline` tag —— 这正好就是"留一个上游 diff 点"那条建议，
     它一直在那儿，只是没人标记。
   - 远端 `origin` 改名 `upstream`：它指向 `dondch/OpenGD77-AES256`，**是别人的仓库**，
     谁手滑 `git push` 就推过去了。
   - 新建分支 `md-uv390-plus`，两周工作提交为 `416025b`。
   - 项目层（`tools/`、文档、控制端、码表）单独建库，`.gitignore` 明确排除
     TYT 捐赠固件、flash 备份、字库 blob、第三方源码树、9.3 GB 工具链。

## D. 静噪常数收口（已完成）

常数搬进 `trx.h`，并让**电台直接把算好的门限报出来**：`0x99` 回应加两字节
（第 19 = `trxGetAnalogSquelchThreshold()`，第 20 = `TRX_SQUELCH_HIST`），长度 19 -> 21。
两个主机工具删掉本地副本，改读电台的值。唯一来源是电台，不可能再漂。
实机验过：`门限=40` 由电台自报，与实测值（UHF 默认 11 档 -> 70-10x3）一致。

搬运时踩了一脚：常数被放进了 `#if defined(ENABLE_SPECTRUM)` 块里，
于是开诊断能编、stock 编不过 —— **是新加的 CI 组合矩阵第一次本地跑就抓到的**。

## E. strncat 边界（已完成）

不是 2 处，是 **14 处**（7 个菜单文件 x 2）。`strncat(d, s, n)` 的 `n` 是"还能再追加多少"，
不是目标大小，而且它还会在其后写结束符 —— 所以 `strncat(d, s, sizeof d)` 最多写
`strlen(d) + sizeof(d) + 1` 字节，目标是 `char[17]` 时可达 34 字节。

一直没出事是因为追加的单位串只有一两个字符、目标通常也不满。那是运气不是安全，
而**中文菜单让它更危险**：GB2312 双字节，左侧很容易占满 16 字节。
加 `SCREEN_STRNCAT(dst, src)` 宏（边界 `sizeof(dst) - strlen(dst) - 1`），14 处全换，
重编后 strncat 警告归零，RAM 不变。

## F. CI 从"一个 AES 矩阵"变成"8 种组合"（已完成）

今天两个组合 bug 都是**手动回归编译**抓到的，不是 CI —— 而 CI 只测 `ENABLE_AES` 的
两个值，那 15 个功能开关的任何组合都没编过。

重写成 8 行矩阵，**每一行都注明它守的是哪个 bug**（诊断不开频谱、提醒不开闹钟、
stock 需显式带 `ENABLE_SAT_ALARM=1`……），并把断言从"大小够不够"升级成
"**codec 窗口确实全 0xFF**"，再加一步打印 RAM 余量（链接器只在溢出时报错，
不会告诉你还剩多少，而那才是决定下个功能做不做得成的数字）。

### 顺带修掉一个会让 CI 随机变红的竞态

本地跑矩阵时三个组合失败、串行重跑却全过。原因不在代码：每条编译规则里各有一句
`@mkdir -p $(dir $@)`，在 Windows/MSYS 上几十个进程同时创建同一个父目录会零星失败，
之后编译器往不存在的路径写 .o，最后表现成链接期 undefined reference 或干脆没有产物
—— **跟真正的代码错误长得一模一样**。

改成一次性建好所有目录（order-only 前置依赖 `$(BUILD)/.dirs`）。
CI 用的是 `make -j$(nproc)`，**一个随机变红的 CI 比没有 CI 更糟** —— 大家会开始无视它。
