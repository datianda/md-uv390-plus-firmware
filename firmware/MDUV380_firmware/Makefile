# Auto-generated Makefile to build OpenGD77 MD-UV390 PLUS 10W firmware
# (mirrors STM32CubeIDE config MDUV380_10W_PLUS_FW). arm-none-eabi-gcc.
TARGET   = openuv380-10w
BUILD    = build
CROSS    = arm-none-eabi-
CC       = $(CROSS)gcc
OBJCOPY  = $(CROSS)objcopy
SIZE     = $(CROSS)size

CPU   = -mcpu=cortex-m4 -mthumb -mfpu=fpv4-sp-d16 -mfloat-abi=hard
ENABLE_AES ?= 0
GITVERSION := $(shell git rev-parse --short HEAD 2>/dev/null || echo UNKNOWN)
DEFS  = -DGITVERSION=$(GITVERSION) -DUSE_HAL_DRIVER -DSTM32F405xx -DPLATFORM_MDUV380 -DPLATFORM_VARIANT_UV380_PLUS_10W -DNDEBUG
INCS  = -I. -ICore/Inc \
        -IDrivers/CMSIS/Device/ST/STM32F4xx/Include -IDrivers/CMSIS/Include \
        -IDrivers/STM32F4xx_HAL_Driver/Inc -IDrivers/STM32F4xx_HAL_Driver/Inc/Legacy \
        -IMiddlewares/ST/STM32_USB_Device_Library/Class/CDC/Inc \
        -IMiddlewares/ST/STM32_USB_Device_Library/Core/Inc \
        -IMiddlewares/Third_Party/FreeRTOS/Source/CMSIS_RTOS_V2 \
        -IMiddlewares/Third_Party/FreeRTOS/Source/include \
        -IMiddlewares/Third_Party/FreeRTOS/Source/portable/GCC/ARM_CM4F \
        -IUSB_DEVICE/App -IUSB_DEVICE/Target -Iapplication/include

ifeq ($(ENABLE_AES),1)
DEFS += -DENABLE_AES
endif

ifeq ($(ENABLE_DMR_DATA),1)
DEFS += -DENABLE_DMR_DATA
endif

ifeq ($(DMR_AES_DIAG_PATTERN),1)
DEFS += -DDMR_AES_DIAG_PATTERN
endif

ifeq ($(DMR_AES_DIAG_ENCPAT),1)
DEFS += -DDMR_AES_DIAG_ENCPAT
endif

ifeq ($(DMR_AES_DIAG_RX),1)
DEFS += -DDMR_AES_DIAG_RX
endif

# Dev-only: USB display mirror + remote key injection (fbmirror.py / rkey.py).
# Lets a PC drive the UI and read the framebuffer over USB. Never enable in a
# release build. Independent of ENABLE_AES.
ifeq ($(ENABLE_KEY_INJECTION),1)
DEFS += -DENABLE_KEY_INJECTION
endif

# Dev-only: swept-RSSI receiver driven over USB (tools/sweep.py). NOT an SDR --
# the AT1846S has no IQ output, only an RSSI register. Never enable in a release
# build. Independent of ENABLE_AES / ENABLE_DMR_DATA / ENABLE_KEY_INJECTION.
ifeq ($(ENABLE_SPECTRUM),1)
DEFS += -DENABLE_SPECTRUM
endif

# Dev-only: DWT scan-step profiler (CPS 0xA9, tools/scanprof.py). Costs 544 bytes of RAM
# for the slot table, which is a lot on a target with under 2 KB spare, so it is separate
# from ENABLE_SPECTRUM -- the sweep tooling is worth keeping when the profiler is not.
# Requires ENABLE_SPECTRUM: the implementation lives in spectrum.c.
ifeq ($(ENABLE_SCAN_PROFILER),1)
DEFS += -DENABLE_SCAN_PROFILER
endif

# Faster ANALOG scanning: adds sub-30 ms steps (20/15/10/6 ms) to the existing
# "Scan dwell time" setting, selectable on the radio and via CHIRP. Digital scanning is
# unchanged (it takes the larger of this and its own DMR timeslot minimum). Unlike
# ENABLE_SPECTRUM this is a user-facing feature flag, not a dev one -- but it is still a
# flag so that a build without it stays byte-identical to stock.
ifeq ($(ENABLE_FAST_SCAN),1)
DEFS += -DENABLE_FAST_SCAN
endif

# ENABLE_WATERFALL: scrolling spectrum history under the sweep trace. The history
# itself is self-contained (it detects the sweep wrap itself), but the frequency
# scale drawn under it needs the column->frequency helper, which lives in the
# ENABLE_FAST_SCAN block - so the scale only appears when both flags are on.
# Off by default like every other flag here.
ifeq ($(ENABLE_WATERFALL),1)
DEFS += -DENABLE_WATERFALL
endif

# ENABLE_UI_STYLE: turns hard-coded screen layout choices (S-meter height, its
# S-unit graduations, colour-by-strength) into settings, stored in their own
# custom-data block and edited from Options -> Theme Options -> UI Style.
# Defaults reproduce the stock look exactly. Colour platforms only.
ifeq ($(ENABLE_UI_STYLE),1)
DEFS += -DENABLE_UI_STYLE
endif

# ENABLE_DOPPLER_READOUT: shows how far Doppler has moved the frequencies, and which
# way, on the satellite tracking screen. The screen already retunes for Doppler and
# prints the corrected frequencies, but not the shift itself - and the shift is the
# thing that tells you where in the pass you are: it starts high, passes through zero
# at closest approach, and ends low. Goes in the 18 blank rows at the bottom.
ifeq ($(ENABLE_DOPPLER_READOUT),1)
DEFS += -DENABLE_DOPPLER_READOUT
endif

# DISABLE_SAT_ALARM: removes the satellite pass ALARM entirely - arming it with
# SK2+Green, the beeping, the wake-from-sleep, and ENABLE_SAT_ALERT's additions. The
# satellite screen itself is untouched: predictions, the polar tracking screen and the
# Doppler-corrected frequencies all stay. Off by default, so a build without it behaves
# exactly as upstream does.
ifeq ($(DISABLE_SAT_ALARM),1)
DEFS += -DDISABLE_SAT_ALARM
endif

# ENABLE_SAT_ALERT: makes the satellite pass alarm announce itself from any screen.
# Upstream's alarm has two lives and neither covers the ordinary one: asleep, the power
# management loop wakes the radio at AOS-60s; awake, menuSatellite's tick beeps - but
# only while that screen is on display. Arm an alarm and then go back to using the
# radio and the pass arrives in silence. Also stops arming from switching the radio
# off, which is only useful when there is no other way to be told.
ifeq ($(ENABLE_SAT_ALERT),1)
DEFS += -DENABLE_SAT_ALERT
endif

# ENABLE_INFO_DENSITY: fills the channel screen's biggest hole with the facts it
# leaves out, and tints the header power level by how loud it is. Measured by reading
# the framebuffer back over USB: 63% of the FM channel screen and 46% of the DMR one
# are entirely blank, and the screen never shows the frequency at all - a channel is
# only ever its name. Off by default like every other flag here.
ifeq ($(ENABLE_INFO_DENSITY),1)
DEFS += -DENABLE_INFO_DENSITY
endif

# ENABLE_THEME_PRESET: a ready-made colour scheme in Options -> Theme Options.
# Upstream's theme system can already recolour 32 items, but its *default* sets every
# one of them to the same foreground colour, so a 160x128 colour panel ships looking
# exactly like the monochrome GD-77 it was ported from - which also means the semantic
# colours elsewhere in this firmware (battery green/amber/red, S-meter zones) collapse
# to black. This adds a second preset the user can pick, and Mono to go back. Only
# FOREGROUND items are touched; see themePresetDay[] for why the backgrounds can't be.
ifeq ($(ENABLE_THEME_PRESET),1)
DEFS += -DENABLE_THEME_PRESET
endif

# ENABLE_BAND_LOG: records each sweep pass (160 RSSI bins + time + GPS fix) into
# the last 2 MB of a 16 MB SPI flash, as a cyclic log. Shares that region with
# the NMEA logger, so the two are mutually exclusive at runtime.
ifeq ($(ENABLE_BAND_LOG),1)
DEFS += -DENABLE_BAND_LOG
endif

CFLAGS  = $(CPU) $(DEFS) $(INCS) -Os -g3 -ffunction-sections -fdata-sections -Wall -MMD -MP
LDSCRIPT = STM32F405VGTX_FLASH.ld
LDFLAGS = $(CPU) -T$(LDSCRIPT) --specs=nano.specs -Wl,--gc-sections -Wl,-Map=$(BUILD)/$(TARGET).map -lc -lm -lnosys

C_SRCS   = $(shell find Core Drivers Middlewares USB_DEVICE application -name *.c ! -name languages_builder.c ! -name *_template.c)
ASM_SRCS = Core/Startup/startup_stm32f405vgtx.s
ASM_SRCS_S = $(shell find application -name *.S)
OBJS = $(addprefix $(BUILD)/,$(C_SRCS:.c=.o)) $(addprefix $(BUILD)/,$(ASM_SRCS:.s=.o)) $(addprefix $(BUILD)/,$(ASM_SRCS_S:.S=.o))
DEPS = $(OBJS:.o=.d)

.DEFAULT_GOAL := all
LINKERDATA_BIN = application/source/linkerdata/codec_bin_section_1.bin
# codec_cleaner ships both as an ELF (.Linux) and a Windows PE (.exe). Upstream
# hardcodes the ELF, which cannot run under Git Bash / MSYS on Windows; pick
# whichever binary is native to this host.
ifeq ($(OS),Windows_NT)
CODEC_CLEANER = codec_cleaner.exe
else
CODEC_CLEANER = codec_cleaner.Linux
endif
$(LINKERDATA_BIN):
	@chmod +x tools/$(CODEC_CLEANER)
	cd application/source/linkerdata && ../../../tools/$(CODEC_CLEANER) -C

$(BUILD)/application/source/dmr_codec/codec_bin.o: $(LINKERDATA_BIN)

all: $(BUILD)/$(TARGET).bin $(BUILD)/$(TARGET).hex

$(BUILD)/%.o: %.c
	@mkdir -p $(dir $@)
	$(CC) $(CFLAGS) -c $< -o $@

$(BUILD)/%.o: %.s
	@mkdir -p $(dir $@)
	$(CC) $(CPU) -c $< -o $@

$(BUILD)/%.o: %.S
	@mkdir -p $(dir $@)
	$(CC) $(CPU) -I. -Iapplication -c $< -o $@

$(BUILD)/$(TARGET).elf: $(OBJS)
	$(CC) $(OBJS) $(LDFLAGS) -o $@
	$(SIZE) $@

$(BUILD)/$(TARGET).bin: $(BUILD)/$(TARGET).elf
	$(OBJCOPY) -O binary $< $@

$(BUILD)/$(TARGET).hex: $(BUILD)/$(TARGET).elf
	$(OBJCOPY) -O ihex $< $@

clean:
	rm -rf $(BUILD)

-include $(DEPS)
