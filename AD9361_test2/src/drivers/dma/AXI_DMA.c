#include "AXI_DMA.h"

XAxiDma AxiDma0;

//中断处理标志
volatile int TxDone;
volatile int RxDone;
volatile int Error;
volatile int TxError;
volatile int RxError;
volatile u32 TxIrqStatusLast;
volatile u32 RxIrqStatusLast;


/*****************************************************************************
* @brief	初始化AXI DMA
* @param	AxiDmaPtr	指向DMA实例的指针
* @param	DeviceId	AXI DMA的设备ID
* @Usage	AXI_DMA_Init(&AxiDma0, XPAR_AXIDMA_0_DEVICE_ID);
******************************************************************************/
void AXI_DMA_Init(XAxiDma *AxiDma, uint32_t DeviceId)
{
	XAxiDma_Config *Config;
	Config = XAxiDma_LookupConfig(DeviceId);
	XAxiDma_CfgInitialize(AxiDma, Config);

	//禁用所有中断
	XAxiDma_IntrDisable(AxiDma, XAXIDMA_IRQ_ALL_MASK, XAXIDMA_DMA_TO_DEVICE);
	XAxiDma_IntrDisable(AxiDma, XAXIDMA_IRQ_ALL_MASK, XAXIDMA_DEVICE_TO_DMA);
}

/*****************************************************************************
* @brief	初始化DMA的Tx中断
* @param	AxiDmaPtr	指向DMA实例的指针
* @param	TxIntrId	TX通道中断ID
* @param	Handler		Tx通道中断处理函数
* @Usage	AXI_DMA_TxInt_Init(&AxiDma, TX_INTR_ID, TxIntrHandler);
******************************************************************************/
void AXI_DMA_TxInt_Init(XAxiDma *AxiDma, uint16_t TxIntrId, Xil_InterruptHandler Handler)
{
	//连接中断服务函数
	Set_ScuGic_Link(TxIntrId, 0xA0, Rising_Edge_Sensitive, Handler, (void *)AxiDma);

	//使能DMATx中断
	XAxiDma_IntrEnable(AxiDma, XAXIDMA_IRQ_ALL_MASK, XAXIDMA_DMA_TO_DEVICE);
}

/*****************************************************************************
* @brief	初始化DMA的Rx中断
* @param	AxiDmaPtr	指向DMA实例的指针
* @param	RxIntrId	Rx通道中断ID
* @param	Handler		Rx通道中断处理函数
* @Usage	AXI_DMA_RxInt_Init(&AxiDma, RX_INTR_ID, RxIntrHandler);
******************************************************************************/
void AXI_DMA_RxInt_Init(XAxiDma *AxiDma, uint16_t RxIntrId, Xil_InterruptHandler Handler)
{
	//连接中断服务函数
	Set_ScuGic_Link(RxIntrId, 0xA0, Rising_Edge_Sensitive, Handler, (void *)AxiDma);

	//使能DMARx中断
	XAxiDma_IntrEnable(AxiDma, XAXIDMA_IRQ_ALL_MASK,XAXIDMA_DEVICE_TO_DMA);
}

/*********************************************************************
********
* @brief DMA TX 中断处理函数。
* 从硬件获取中断状态，对其进行确认：
* 如果发生任何错误，它将重置硬件。
* 如果中断完成，则将 TxDone 标志置为 1
*
* @param Callback 是指向 DMA 引擎的 TX 通道的指针。
**********************************************************************
********/
void TxIntrHandler(void *Callback)
{
	u32 IrqStatus;
	int TimeOut;
	XAxiDma *AxiDmaInst = (XAxiDma *)Callback;

	//读取挂起的中断，获取被声明的中断的位掩码
	IrqStatus = XAxiDma_IntrGetIrq(AxiDmaInst, XAXIDMA_DMA_TO_DEVICE);
	TxIrqStatusLast = IrqStatus;

	//确认挂起的中断
	XAxiDma_IntrAckIrq(AxiDmaInst, IrqStatus, XAXIDMA_DMA_TO_DEVICE);

	//如果没有中断被断言，直接返回
	if (!(IrqStatus & XAXIDMA_IRQ_ALL_MASK))
	{
		return;
	}

	//如果断言中断错误，则拉高错误标志位，复位硬件以从错误中恢复，然后直接返回
	if ((IrqStatus & XAXIDMA_IRQ_ERROR_MASK))
	{
		Error = 1;//将错误标志置为 1
		TxError = 1;

		//复位 DMA 通道
		XAxiDma_Reset(AxiDmaInst);

		//装载循环计数器复位的超时次数
		TimeOut = RESET_TIMEOUT_COUNTER;

		//等待 DMA 复位完成，若复位超时则也会跳出等待，超时次数由开头用户自定义

		while (TimeOut)
		{
			if (XAxiDma_ResetIsDone(AxiDmaInst))//如果复位完成，则 break跳出 while 循环
			{
				break;
			}

			TimeOut --;//超时次数减一，达到 0 时，while 循环也会跳出
		}

		return;
	}

	//如果中断完成，则将 TxDone 标志置为 1
	if ((IrqStatus & XAXIDMA_IRQ_IOC_MASK))
	{
		TxDone = 1;//将发送完成标志置为 1
	}
}


/*********************************************************************
********
* @brief DMA RX 中断处理函数
* 它从硬件获取中断状态，对其进行确认：
* 如果发生任何错误，它将重置硬件。
* 否则，如果中断完成，则将 RxDone 标志置为 1。
*
* @param Callback 是指向 DMA 引擎的 RX 通道的指针。
**********************************************************************
********/
void RxIntrHandler(void *Callback)
{
	u32 IrqStatus;
	int TimeOut;
	XAxiDma *AxiDmaInst = (XAxiDma *)Callback;

	//读取挂起的中断
	IrqStatus = XAxiDma_IntrGetIrq(AxiDmaInst, XAXIDMA_DEVICE_TO_DMA);
	RxIrqStatusLast = IrqStatus;

	//确认挂起的中断
	XAxiDma_IntrAckIrq(AxiDmaInst, IrqStatus, XAXIDMA_DEVICE_TO_DMA);

	//如果没有中断被断言，直接返回
	if (!(IrqStatus & XAXIDMA_IRQ_ALL_MASK))
	{
		return;
	}

	/*
	 * 如果断言中断错误，则将错误标志置 1，
	 * 复位硬件以从错误中恢复，然后直接返回
	 * */

	if ((IrqStatus & XAXIDMA_IRQ_ERROR_MASK))
	{
		Error = 1;//将错误标志置为 1
		RxError = 1;
		XAxiDma_Reset(AxiDmaInst);
		TimeOut = RESET_TIMEOUT_COUNTER;

		//等待 DMA 复位完成，若复位超时也会跳出等待，超时次数由开头用户自定义
		while (TimeOut)
		{
			if(XAxiDma_ResetIsDone(AxiDmaInst))//如果复位完成，则 break跳出 while 循环
			{
				break;
			}
			TimeOut -= 1;//超时次数减一，达到 0 时，while 循环也会跳出
		}
		return;
	}

	//如果中断完成，则将 RxDone 标志置为 1
	if ((IrqStatus & XAXIDMA_IRQ_IOC_MASK))
	{
		RxDone = 1;//将接收完成标志置为 1
	}
}





