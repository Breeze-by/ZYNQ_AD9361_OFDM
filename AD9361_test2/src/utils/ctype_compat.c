#include <stdint.h>

/*
 * Xilinx standalone xil_printf in the checked-in BSP archive expects the
 * legacy __ctype_ptr__ symbol. The local GNU Arm toolchain exports _ctype_
 * instead, so provide a compatibility alias from the application side.
 */
extern const char _ctype_[];

const char *__ctype_ptr__ = _ctype_;
