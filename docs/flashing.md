# 让 Claude 自己刷固件

目标：改完固件我自己刷、自己开扫描、自己截图验收，不用你在回路里。

## 为什么非要动驱动

刷机走 DFU，DFU 要用 libusb 说话，Windows 上 libusb 要求设备绑的是 WinUSB
这类驱动。你现在 DFU 设备绑的是 ST 的 **STTub30**（DfuSe 装的），libusb 打不开。

我先试过**不动驱动**的路子：你机器上有 `DfuSeCommand.exe`（DfuSe 自带的命令行版），
用的就是 STTub30。但看了上游烧录器的源码后放弃了 —— TYT 的 bootloader 不是标准 DfuSe：

- 整个镜像要先用 `MDUV380_ENCODE_CIPHER` 逐字节异或加密，bootloader 写入时才解密；
- 擦写之前要发两条私有命令 `0x91 0x01` / `0x91 0x31`，标准 DfuSe 工具不会发。

拿你的电台赌这个不值得，所以走 Zadig + 上游那个经过验证的烧录器。

## 代价（先说清楚）

换成 WinUSB 之后：

- **DfuSe 图形界面（DfuSeDemo）看不到电台了** —— 以后备份 flash 得走别的路；
- **CPS 的 Firmware loader 也刷不了了** —— 它同样走 STTub30。

两条都能恢复：设备管理器 → 找到该设备 → 更新驱动程序 →
浏览 → **从计算机上的可用驱动程序列表中选取** → 选 `STM Device in DFU Mode`。
换回来 CPS 和 DfuSe 就又能用了。

## 操作步骤（换驱动只做这一次，进 DFU 每次都要）

**1. 让电台进 DFU 模式**

用你之前做 DfuSe 备份时进 DFU 的那个组合键（关机，按住组合键再开机）。
屏幕不亮是正常的，DFU 模式没有界面 —— **别拿屏幕判断**，看电脑：
设备管理器里冒出 `STM Device in DFU Mode` 才算进去了。
或者直接让我跑 `python tools/flash.py --list` 替你确认。

> **必须手动进。** 我原本写了一条 CPS 命令 `0x9F` 想免按键进 DFU
> （把 app 的初始栈指针的有效位清掉，bootloader 就不肯离开 DFU），
> **在这台电台上不工作** —— 实测见下面「0x9F 为什么没用」。

**2. 跑 Zadig**

`zadig-2.9.exe`（从 <https://zadig.akeo.ie/> 下载），**右键以管理员身份运行**。

1. 菜单 `Options` → 勾上 **List All Devices**（不勾看不到已经有驱动的设备）
2. 下拉框里选 `STM32 BOOTLOADER` 或 `STM Device in DFU Mode`
3. **核对 USB ID 是 `0483` `DF11`** —— 对不上就别点
4. 右边目标驱动选 **WinUSB**，点 `Replace Driver`

> ⚠️ **绝对不要碰 `OpenGD77 (COM13)` / USB ID `1FC9 0094`。**
> 那是正常模式的串口，换了驱动 CPS 和控制端全挂。
> Zadig 界面上只会显示当前插着的设备，所以第 1 步进 DFU 之后，
> 正常模式那个串口本来就不在列表里 —— 但还是核对一遍 USB ID。

**3. 断电重开，回正常模式**

然后告诉我一声，我跑 `python tools/flash.py --list` 确认能看到设备。

## 之后我怎么刷

```bash
python tools/flash.py <某个.bin>          # 预检，不写入
python tools/flash.py <某个.bin> --yes    # 真刷
```

顺序是：**（你先手动把电台弄进 DFU）** → 等 `0483:DF11` 出现 →
交给上游 `opengd77_stm32_firmware_loader.py`（它做 codec 合并 + 加密下载）→
等 CDC 端口回来 → 读固件信息确认。

喂给它的是**未合并 codec 的原始 .bin**，合并由烧录器做，和 CPS 一模一样。

## 0x9F 为什么没用

实测：命令发出去，`HAL_FLASH_Program` 返回 `HAL_OK`，`HAL_FLASH_GetError()` 是 0，
**但那个字根本没变**（读回来仍是 `0x2001FFFC`），重启照样进正常模式。

```
!! 0x9F 没能生效：SP 字仍是 0x2001FFFC（有效），电台不会进 DFU。
   HAL=0  FLASH error=0x00000000  FLASH->SR=0x00000004
```

整个 OpenGD77 里**只有这一处**写内部 flash，所以这条路上游从来没验证过。
最可能的原因是 TYT 的 bootloader 给 app 那几个扇区上了写保护（WRP），
只在 DFU 模式下解开 —— 也就是说「从运行中的固件把自己踢进 DFU」这条路本身走不通。

上游 tools 里的 `dmr_reboot_dfu.py`（CPS 命令 `0x90`）也不行 —— 它跳的是
**STM32 的 ROM bootloader**（`0x1FFF0000`），而这台用的是 TYT 自己那个。
证据：DFU 设备报的内存布局从 `0x800c000` 起（ROM bootloader 会报整个 `0x08000000`/1MB）。

已经改成明确报错而不是干等一个永远不会出现的设备。

**所以每次刷机都要你手动进一次 DFU。** 唯一可能的自动化路子是让 app 直接跳进
TYT bootloader 里 DFU 循环的入口（绕过按键检查），需要先把那段反汇编清楚，
有风险，优先级不高。

## 刷坏了怎么办

刷到一半断了，电台是停在 DFU，不是砖 —— bootloader 在 `0x08000000`，
我们只写 `0x0800C000` 往上，碰不到它。直接重跑 `flash.py` 就行。

真要退回 CPS 刷：先按上面「代价」那节把驱动换回 STTub30。

## 已经验证过的部分

| 项 | 怎么验的 | 结果 |
|---|---|---|
| codec 合并复现了 CPS 的 `Patching for DMR` | 把电台里正在跑的固件从 MCU ROM 读回来（297904 字节），跟离线合并结果比 SHA256 | **逐字节一致** |
| 拼接偏移 `0x6937C` 是固定的 | 链接脚本里 `. = ABSOLUTE(0x807537C)` | 钉死，不随代码大小变 |
| MCU ROM 寻址 | 读 `0x0` 得到 bootloader 向量表，app 在 `0xC000` | 0 = `0x08000000` |
| `0x9F` 免按键进 DFU | 实测发命令后 SP 字未变、重启进正常模式 | **不可用**，见上 |
| libusb 后端 | `pip install libusb-package`，能枚举 13 个设备 | 通 |
| DFU 传输 | — | **等换驱动** |
