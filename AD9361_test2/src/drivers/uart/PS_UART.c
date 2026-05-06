/**
  *****************************************************************************
  *                         PS UART Driver
  *****************************************************************************
  *
  * 使用方式：
  *
  * UART_Init(115200);
  * UART_Printf("hello\r\n");
  * UART_Printf("num = %d, value = %.2f\r\n", num, value);
  *
  *****************************************************************************
**/

#include "PS_UART.h"

#include <stdio.h>
#include <string.h>
#include <stdarg.h>

/*
 * UART 设备实例，放在驱动内部。
 * 外部不需要再关心 &UartPs1。
 */
static XUartPs UartPs1;


/**
 * @brief 初始化默认 PS UART
 *
 * @param BaudRate 波特率，例如 115200
 */
void UART_Init(uint32_t BaudRate)
{
    XUartPs_Config *Config;

    Config = XUartPs_LookupConfig(PS_UART_DEVICE_ID);
    if (Config == NULL)
    {
        return;
    }

    XUartPs_CfgInitialize(&UartPs1, Config, Config->BaseAddress);

    XUartPs_SetBaudRate(&UartPs1, BaudRate);

    XUartPs_SetOperMode(&UartPs1, XUARTPS_OPER_MODE_NORMAL);
}


/**
 * @brief 发送字符串
 *
 * @param str 要发送的字符串
 */
void UART_SendString(const char *str)
{
    if (str == NULL)
    {
        return;
    }

    XUartPs_Send(&UartPs1, (uint8_t *)str, strlen(str));

    while (XUartPs_IsSending(&UartPs1));
}


/**
 * @brief 类似 printf 的串口打印函数
 *
 * 支持：
 * %d      int
 * %u      unsigned int
 * %x/%X   十六进制
 * %c      字符
 * %s      字符串
 * %f      浮点数，需要开启 printf 浮点支持
 *
 * @param fmt 格式化字符串
 *
 * @return 实际发送的字符数
 */
int UART_Printf(const char *fmt, ...)
{
    char buffer[256];
    va_list args;
    int len;

    if (fmt == NULL)
    {
        return -1;
    }

    va_start(args, fmt);

    len = vsnprintf(buffer, sizeof(buffer), fmt, args);

    va_end(args);

    if (len < 0)
    {
        return len;
    }

    /*
     * 如果格式化后的字符串超过 buffer 大小，
     * vsnprintf 会截断字符串。
     */
    if (len >= (int)sizeof(buffer))
    {
        len = sizeof(buffer) - 1;
    }

    XUartPs_Send(&UartPs1, (uint8_t *)buffer, len);

    while (XUartPs_IsSending(&UartPs1));

    return len;
}


/**
 * @brief 发送原始字节数据
 *
 * 适合发送协议帧、二进制数据。
 * 例如 0xA5 0x5A 0x01 0x02。
 *
 * @param data 数据指针
 * @param len  数据长度
 *
 * @return 实际发送的字节数
 */
int UART_SendBytes(const uint8_t *data, uint32_t len)
{
    int sent_len;

    if (data == NULL || len == 0)
    {
        return 0;
    }

    sent_len = XUartPs_Send(&UartPs1, (uint8_t *)data, len);

    while (XUartPs_IsSending(&UartPs1));

    return sent_len;
}


/**
 * @brief 接收原始字节数据
 *
 * 注意：
 * XUartPs_Recv 是非阻塞的。
 * 它会返回当前实际收到的字节数，不一定等于 len。
 *
 * @param buffer 接收缓冲区
 * @param len    希望接收的最大长度
 *
 * @return 实际接收到的字节数
 */
int UART_RecvBytes(uint8_t *buffer, uint32_t len)
{
    if (buffer == NULL || len == 0)
    {
        return 0;
    }

    return XUartPs_Recv(&UartPs1, buffer, len);
}
