#ifndef _AXI_DMA_H_
#define _AXI_DMA_H_

#include "COMMON.h"
#include "SCU_GIC.h"
#include "xaxidma.h"

extern volatile int TxDone;
extern volatile int RxDone;
extern volatile int Error;
extern volatile int TxError;
extern volatile int RxError;
extern volatile u32 TxIrqStatusLast;
extern volatile u32 RxIrqStatusLast;
extern volatile u32 TxDmaSrLast;
extern volatile u32 RxDmaSrLast;
extern volatile u32 TxDmaCrLast;
extern volatile u32 RxDmaCrLast;
extern volatile u32 TxDmaBuffLenLast;
extern volatile u32 RxDmaBuffLenLast;

#define RESET_TIMEOUT_COUNTER 10000

extern XAxiDma AxiDma0;

void AXI_DMA_Init(XAxiDma *AxiDma, uint32_t DeviceId);
void AXI_DMA_TxInt_Init(XAxiDma *AxiDma, uint16_t TxIntrId, Xil_InterruptHandler Handler);
void AXI_DMA_RxInt_Init(XAxiDma *AxiDma, uint16_t RxIntrId, Xil_InterruptHandler Handler);
void TxIntrHandler(void *Callback);
void RxIntrHandler(void *Callback);

#endif /* _AXI_DMA_H_ */
