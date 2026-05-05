#ifndef ZYNQ7010_LIB_SCU_GIC_H_
#define ZYNQ7010_LIB_SCU_GIC_H_

#include "COMMON.h"

#define HIGH_Level_Sensitive 0x01
#define Rising_Edge_Sensitive 0x03

extern XScuGic ScuGic;

void ScuGic_Init(void);
void Set_ScuGic_Link(uint16_t IntrId, uint8_t Priority, uint8_t Trigger,
    Xil_InterruptHandler Handler, void *CallBackRef);

#endif /* ZYNQ7010_LIB_SCU_GIC_H_ */
