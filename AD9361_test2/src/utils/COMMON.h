#ifndef ZYNQ7010_LIB_COMMON_H_
#define ZYNQ7010_LIB_COMMON_H_

#include <math.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "xil_cache.h"
#include "xil_exception.h"
#include "xil_types.h"
#include "xparameters.h"
#include "xscugic.h"
#include "xscutimer.h"

#define CPU_CLK_HZ XPAR_PS7_CORTEXA9_0_CPU_CLK_FREQ_HZ
#define INPUT 1
#define OUTPUT 0
#define REG8 8
#define REG16 16

#endif /* ZYNQ7010_LIB_COMMON_H_ */
