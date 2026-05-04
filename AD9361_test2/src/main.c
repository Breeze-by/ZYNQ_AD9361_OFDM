#include "COMMON.h"
#include "AXI_DMA.h"
#include "SCU_GIC.h"

#include "config.h"
#include "ad9361_api.h"
#include "ad9361.h"
#include "parameters.h"
#include "platform.h"
#include <xil_cache.h>
#include "xil_io.h"
#include "spi_ctrl.h"
#include "io_control.h"
#include "gpio_initial.h"
#include "radio_set.h"
#include "ad9361_config.h"
#include "xscugic.h"

#include <stdio.h>
#include "math.h"

#define PI 3.14159265358979323846
#define ARRAY_LENGTH 2000        // 数组长度
#define BITS 12                 // 数据位宽
#define AMPLITUDE ((1 << (BITS - 1)) - 1) // 振幅，确保不溢出 (2^11 -1 = 2047)

//#define TRANS_LENGTH 256 //发送长度，这里最大值为 2^16-1=65535

#define RX_INTR_ID XPAR_FABRIC_AXIDMA_0_S2MM_INTROUT_VEC_ID //RX的中断号
#define TX_INTR_ID XPAR_FABRIC_AXIDMA_0_MM2S_INTROUT_VEC_ID //TX的中断号

#define TX_BUFFER_BASE 0x1200000 //TX 缓冲区的基地址
#define RX_BUFFER_BASE 0x1400000 //RX 缓冲区的基地址

int main(void)
{
	//这里开始测试将AD9361的配置移植进去
	Xil_ICacheDisable();
	Xil_DCacheDisable();

	gpio_initial();

	default_init_param.gpio_resetb = RESETB;
	default_init_param.gpio_sync = -1;
	default_init_param.gpio_cal_sw1 = -1;
	default_init_param.gpio_cal_sw2 = -1;
	spi_init(SPI_DEVICE_ID, 1, 0);
	ad9361_init(&ad9361_phy, &default_init_param);
	ad9361_spi_write(ad9361_phy->spi, REG_TX_CLOCK_DATA_DELAY, 0x40);
	int32_t val;
	val=ad9361_config(ad9361_phy);
	//截止这里是移植的基础配置

	UART_Init(115200);
	int i = 0;
	for (i = 0; i < 10 ; i ++)
	{
		UART_Printf("1234567\r\n");
	}

	int Index; //计数变量
	uint16_t Error_Cnt = 0; //错误计数
	uint64_t *TxBufferPtr; //传输数据的指针
	uint64_t *RxBufferPtr; //接收数据的指针

	//将指针 TxBufferPtr 指向 TX_BUFFER_BASE
	TxBufferPtr = (uint64_t *)TX_BUFFER_BASE;
	//将指针 RxBufferPtr 指向 RX_BUFFER_BASE
	RxBufferPtr = (uint64_t *)RX_BUFFER_BASE;

	//初始化通用中断控制器
	ScuGic_Init();

	//初始化 AXI DMA
	AXI_DMA_Init(&AxiDma0, XPAR_AXIDMA_0_DEVICE_ID);

	//设置中断服务函数
	AXI_DMA_TxInt_Init(&AxiDma0, TX_INTR_ID, TxIntrHandler);
	AXI_DMA_RxInt_Init(&AxiDma0, RX_INTR_ID, RxIntrHandler);

	// 生成正弦波数组
	for (int i = 0; i < ARRAY_LENGTH; i++)
	{
		// 1. 计算正弦值：sin(2 * PI * i / ARRAY_LENGTH) 生成一个完整的周期
		double sin_value1 = sin(10 * PI * i / ARRAY_LENGTH);
		// 2. 缩放到12位有符号整数范围 (-2048 到 2047)
		//    先乘以振幅AMPLITUDE(2047)，将范围缩放到-2047到2047，然后四舍五入到最接近的整数
		double scaled_value1 = sin_value1 * AMPLITUDE;
		short rounded_value1 = (short)((scaled_value1 > 0) ? (scaled_value1 + 0.5) : (scaled_value1 - 0.5));

		// 1. 计算正弦值：sin(2 * PI * i / ARRAY_LENGTH) 生成一个完整的周期
		double sin_value2 = sin(100 * PI * i / ARRAY_LENGTH);
		// 2. 缩放到12位有符号整数范围 (-2048 到 2047)
		//    先乘以振幅AMPLITUDE(2047)，将范围缩放到-2047到2047，然后四舍五入到最接近的整数
		double scaled_value2 = sin_value2 * AMPLITUDE;
		short rounded_value2 = (short)((scaled_value2 > 0) ? (scaled_value2 + 0.5) : (scaled_value2 - 0.5));
		// 3. 存储到数组
		TxBufferPtr[i] = ((uint64_t)((rounded_value1)&0xfff)) + (((uint64_t)((rounded_value2)&0xfff)) <<12) + (((uint64_t)((rounded_value1)&0xfff)) <<24) + (((uint64_t)((rounded_value2)&0xfff)) <<36);
	}

	while(1)
	{
		//在开始传输测试之前清除中断状态标志
		TxDone = 0;
		RxDone = 0;
//		Error = 0;

		//在 DMA 传输之前刷新 Buffer
		Xil_DCacheFlushRange((UINTPTR)TxBufferPtr, ARRAY_LENGTH*8);
		Xil_DCacheFlushRange((UINTPTR)RxBufferPtr, 400*8);

		//开启数据传输
		XAxiDma_SimpleTransfer(&AxiDma0,(UINTPTR) RxBufferPtr,400*8, XAXIDMA_DEVICE_TO_DMA);
		XAxiDma_SimpleTransfer(&AxiDma0,(UINTPTR) TxBufferPtr,ARRAY_LENGTH*8, XAXIDMA_DMA_TO_DEVICE);

		//等待 TX 完成、或者 RX 完成、或者传输错误，否则一直等待
		while (!TxDone)//&& !RxDone
		{
			/* 等待 */
		}

		//等待 TX 完成、或者 RX 完成、或者传输错误，否则一直等待
		while (!RxDone)//&& !RxDone
		{
			/* 等待 */
		}

	}
}


