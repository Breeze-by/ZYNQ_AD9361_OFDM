#ifndef PS_UART_H_
#define PS_UART_H_

#include "COMMON.h"
#include "xuartps.h"
#include "xparameters.h"

#include <stdint.h>

/*
 * 当前工程里只有 XPAR_PS7_UART_0_DEVICE_ID，
 * 所以默认使用 PS UART0。
 */
#define PS_UART_DEVICE_ID XPAR_PS7_UART_0_DEVICE_ID

#define PS_UART_DEFAULT_BAUDRATE 115200

void UART_Init(uint32_t BaudRate);

void UART_SendString(const char *str);

int UART_Printf(const char *fmt, ...);

int UART_SendBytes(const uint8_t *data, uint32_t len);

int UART_RecvBytes(uint8_t *buffer, uint32_t len);

#endif /* PS_UART_H_ */
