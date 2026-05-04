#ifndef _AXI_DMA_H_
#define _AXI_DMA_H_

#include "COMMON.h"
#include "xaxidma.h"

extern volatile int TxDone;
extern volatile int RxDone;
extern volatile int Error;


//循环计数器复位的超时次数
#define RESET_TIMEOUT_COUNTER	10000

extern XAxiDma AxiDma0;

void AXI_DMA_Init(XAxiDma *AxiDma, uint32_t DeviceId);
void AXI_DMA_TxInt_Init(XAxiDma *AxiDma, uint16_t TxIntrId, Xil_InterruptHandler Handler);
void AXI_DMA_RxInt_Init(XAxiDma *AxiDma, uint16_t RxIntrId, Xil_InterruptHandler Handler);
void TxIntrHandler(void *Callback);
void RxIntrHandler(void *Callback);



#endif /* _AXI_DMA_H_ */
