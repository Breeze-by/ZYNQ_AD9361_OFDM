#ifndef ZYNQ7010_LIB_SCU_TIMER_H_
#define ZYNQ7010_LIB_SCU_TIMER_H_

#include "COMMON.h"
#include "SCU_GIC.h"

extern XScuTimer ScuTimer;

void ScuTimer_IRQ_Handler(void *CallBackRef);
void ScuTimer_Int_Init(double Load_Val);

#endif /* ZYNQ7010_LIB_SCU_TIMER_H_ */
