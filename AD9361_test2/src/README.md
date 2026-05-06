# AD9361_test2 Source Layout

This application project is organized so that only `AD9361_test2` contains user-maintained code. BSP and hardware-exported projects remain untouched.

## Directory Structure

```text
src/
|-- app/
|   |-- app_config.h
|   `-- main.c
|-- drivers/
|   |-- ad9361/
|   |-- dma/
|   |-- interrupt/
|   |-- timer/
|   `-- uart/
|-- utils/
|-- lscript.ld
`-- Xilinx.spec
```

## Module Responsibilities

- `app/main.c`
  Application entry point. It keeps the original boot, AD9361 bring-up, DMA transfer, lwIP polling, UART print, and interrupt initialization flow unchanged.

- `app/app_config.h`
  Application-level constants used by `main.c`, such as DMA buffer addresses, transfer lengths, waveform parameters, and static Ethernet settings.

- `drivers/ad9361/`
  AD9361 driver stack and platform adaptation layer.
  Main files:
  - `ad9361.c/.h`, `ad9361_api.c/.h`
  - `platform.c/.h`
  - `spi_ctrl.c/.h`
  - `ad9361_config.h`, `radio_set.h`, `parameters.h`, `gpio_initial.h`, `io_control.h`, `config.h`, `common1.h`

- `drivers/dma/`
  AXI DMA initialization and TX/RX interrupt handlers.
  Main files:
  - `AXI_DMA.c/.h`

- `drivers/uart/`
  PS UART wrapper used for formatted debug output and raw TX/RX access.
  Main files:
  - `PS_UART.c/.h`

- `drivers/interrupt/`
  SCU GIC wrapper and user interrupt handlers.
  Main files:
  - `SCU_GIC.c/.h`
  - `ISR.c/.h`

- `drivers/timer/`
  SCU private timer wrapper.
  Main files:
  - `SCU_TIMER.c/.h`

- `utils/`
  Shared utility code and common platform includes.
  Main files:
  - `COMMON.c/.h`
  - `util.c/.h`

## Where To Modify Features Later

- Change AD9361 initialization parameters, FIR, LO, bandwidth, gain, or GPIO RF path selection:
  - `utils/COMMON.c`
  - `drivers/ad9361/*.h`

- Change DMA initialization, TX/RX done handling, or DMA error recovery:
  - `drivers/dma/AXI_DMA.c`
  - `drivers/dma/AXI_DMA.h`

- Change UART print or serial I/O helpers:
  - `drivers/uart/PS_UART.c`
  - `drivers/uart/PS_UART.h`

- Change interrupt controller setup or user ISR behavior:
  - `drivers/interrupt/SCU_GIC.c`
  - `drivers/interrupt/ISR.c`

- Change private timer setup or timer interrupt hookup:
  - `drivers/timer/SCU_TIMER.c`
  - `drivers/timer/SCU_TIMER.h`

- Change only application constants without touching flow:
  - `app/app_config.h`

## Build Notes

- The SDK project file `.cproject` now points to the new source include directories under `src/`.
- `lscript.ld` and `Xilinx.spec` remain in `src/` to avoid changing linker behavior.
- No AD9361, SPI, DMA, UART, interrupt, or timer logic was intentionally changed in this reorganization.
