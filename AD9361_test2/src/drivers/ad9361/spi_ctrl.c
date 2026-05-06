/******************************************************************************/
/***************************** Include Files **********************************/
/******************************************************************************/
#include "spi_ctrl.h"

#include "util.h"
#include "platform.h"
#include "parameters.h"
int32_t ad9361_spi_write_m1(struct spi_device *spi, uint32_t reg, uint32_t mask,
		uint32_t offset, uint32_t val) {
	uint8_t buf;
	int32_t ret;

	if (!mask)
		return -EINVAL;

	ret = ad9361_spi_readm(spi, reg, &buf, 1);
	if (ret < 0)
		return ret;

	buf &= ~mask;
	buf |= ((val << offset) & mask);

	return ad9361_spi_write(spi, reg, buf);
}
#define ad9361_spi_write_m(spi, reg, mask, val) \
		ad9361_spi_write_m1(spi, reg, mask, find_first_bit(mask), val)
int32_t ad9361_set_auxdac1(struct ad9361_rf_phy *phy, uint32_t val_mV) {
	uint32_t val, tmp;
	struct spi_device *spi = phy->spi;
	/* Disable DAC if val == 0, Ignored in ENSM Auto Mode */
	ad9361_spi_write_m(spi, REG_AUXDAC_ENABLE_CTRL, AUXDAC_MANUAL_BAR(1),
			val_mV ? 0 : 1);

	if (val_mV < 306)
		val_mV = 306;

	if (val_mV < 1888) {
		val = ((val_mV - 306) * 1000) / 1404; /* Vref = 1V, Step = 2 */
		tmp = AUXDAC_1_VREF(0);
	} else {
		val = ((val_mV - 1761) * 1000) / 1836; /* Vref = 2.5V, Step = 2 */
		tmp = AUXDAC_1_VREF(3);
	}

	val = clamp_t(uint32_t, val, 0, 1023);

	ad9361_spi_write(spi, REG_AUXDAC_1_WORD, val >> 2);
	ad9361_spi_write(spi, REG_AUXDAC_1_CONFIG, AUXDAC_1_WORD_LSB(val) | tmp);
	phy->auxdac1_value = val_mV;
	return 0;
}
