/* Included privately by net_rx.c: bounded UDP control, no RXCFG/ARQ changes.
 * Wire: request 5 little-endian u32; response 65 u32 (last word CRC32).
 * Calibration is EXPLICIT, 10 ms settling + 200 ms capture, never inferred
 * from a failed packet decode. Existing data return headers stay unchanged.
 */
#include "ad9361_api.h"
extern struct ad9361_rf_phy *ad9361_phy;
#define SNR_REQUEST_MAGIC 0x51524e53U
#define SNR_RESPONSE_MAGIC 0x31524e53U
#define SNR_SIGNATURE 0xa7220001U
#define SNR_QUIET_CONFIRM 0x51554945U
#define SNR_HAS_HW 1U
#define SNR_NOISE_VALID 2U
#define SNR_CALIBRATING 4U
#define SNR_CAL_TRAFFIC 8U
#define SNR_CAL_CLIPPED 16U
#define SNR_RF_CHANGED 32U
#define SNR_SNAPSHOT_ERROR 64U
#define SNR_BAD_REQUEST 128U
#define SNR_CAL_EXPIRED 512U

static uint32_t snr_control, snr_epoch, snr_flags;
static uint32_t snr_noise[14], snr_cal_context[7];
static int snr_cal_state;
static XTime snr_cal_started, snr_cal_finished;

static void snr_write_control(uint32_t value)
{
    snr_control = value;
    Xil_Out32(NET_OPENOFDM_RX_REG(6U), value);
    (void)Xil_In32(NET_OPENOFDM_RX_REG(6U));
}

static int snr_context(uint32_t *v)
{
    int32_t gain_db;
    uint8_t mode;
    uint64_t lo;
    if (ad9361_phy == NULL ||
        ad9361_get_rx_rf_gain(ad9361_phy, 0, &gain_db) != 0 ||
        ad9361_get_rx_gain_control_mode(ad9361_phy, 0, &mode) != 0 ||
        ad9361_get_rx_rf_bandwidth(ad9361_phy, &v[2]) != 0 ||
        ad9361_get_rx_sampling_freq(ad9361_phy, &v[3]) != 0 ||
        ad9361_get_rx_lo_freq(ad9361_phy, &lo) != 0) return -1;
    v[0] = (uint32_t)gain_db; v[1] = mode;
    v[4] = (uint32_t)lo; v[5] = (uint32_t)(lo >> 32);
    v[6] = Xil_In32(NET_OPENOFDM_RX_REG(5U));
    return mode == 0U ? 0 : -1; /* Only manual gain is a stable reference. */
}

static int snr_snapshot(uint32_t *words, uint32_t *seq)
{
    unsigned i;
    uint32_t old = Xil_In32(NET_OPENOFDM_RX_REG(22U));
    snr_write_control((snr_control & ~0x1f00U) ^ 4U);
    for (i=0; i<64U; ++i) {
        *seq = Xil_In32(NET_OPENOFDM_RX_REG(22U));
        if (*seq != old) break;
    }
    if (i == 64U) return -1;
    for (i=0; i<14U; ++i) {
        snr_write_control((snr_control & ~0x1f00U) | (i << 8));
        /* AXI read pipeline: complete a control read before data selection. */
        words[i] = Xil_In32(NET_OPENOFDM_RX_REG(28U));
    }
    return Xil_In32(NET_OPENOFDM_RX_REG(22U)) == *seq ? 0 : -1;
}

static void net_snr_poll(void)
{
    XTime now;
    uint32_t seq, context[7];
    if (snr_cal_state == 0) return;
    XTime_GetTime(&now);
    if (snr_cal_state == 1 && net_elapsed_us(snr_cal_started, now) >= 10000ULL) {
        snr_write_control(((snr_control ^ 8U) & ~0x1f03U) | 3U);
        snr_cal_started = now;
        snr_cal_state = 2;
    } else if (snr_cal_state == 2 && net_elapsed_us(snr_cal_started, now) >= 200000ULL) {
        snr_write_control(snr_control & ~1U);
        /* Drain the 3-stage monitor pipeline without a millisecond sleep. */
        (void)Xil_In32(NET_OPENOFDM_RX_REG(6U));
        (void)Xil_In32(NET_OPENOFDM_RX_REG(6U));
        snr_flags = SNR_HAS_HW;
        if (snr_snapshot(snr_noise, &seq) != 0 || snr_noise[0] < 65536U)
            snr_flags |= SNR_SNAPSHOT_ERROR;
        if (snr_noise[8] != 0U) snr_flags |= SNR_CAL_CLIPPED;
        if (snr_noise[9] != 0U) snr_flags |= SNR_CAL_TRAFFIC;
        if (snr_context(context) != 0 || memcmp(context, snr_cal_context, sizeof(context)) != 0)
            snr_flags |= SNR_RF_CHANGED;
        if (snr_flags == SNR_HAS_HW) snr_flags |= SNR_NOISE_VALID;
        snr_cal_finished = now;
        snr_cal_state = 0;
        /* Start a fresh cumulative payload series, retain noise only in PS. */
        snr_write_control(((snr_control ^ 8U) & ~0x1f03U) | 1U);
    }
}

static int net_snr_request(struct pbuf *p, const ip_addr_t *addr, u16_t port)
{
    uint32_t request[5], response[65], context[7], seq=0, magic=0;
    struct pbuf *reply;
    XTime now;
    if (p->tot_len < 4U || pbuf_copy_partial(p, &magic, 4U, 0U) != 4U || magic != SNR_REQUEST_MAGIC)
        return 0;
    /* Malformed requests are ignored, do not allocate response or touch PL. */
    if (p->tot_len != sizeof(request) ||
        pbuf_copy_partial(p, request, sizeof(request), 0U) != sizeof(request) ||
        request[4] != Net_Protocol_Crc32((uint8_t *)request, 16U)) {
        pbuf_free(p); return 1;
    }
    memset(response, 0, sizeof(response));
    memset(context, 0, sizeof(context));
    response[0]=SNR_RESPONSE_MAGIC; response[1]=1U; response[2]=request[1]; response[15]=1U;
    XTime_GetTime(&now);
    if (Xil_In32(NET_OPENOFDM_RX_REG(29U)) == SNR_SIGNATURE) {
        if (snr_flags == 0U) {
            snr_control = Xil_In32(NET_OPENOFDM_RX_REG(6U));
            snr_flags = SNR_HAS_HW;
            snr_epoch = (uint32_t)now;
            snr_write_control(((snr_control ^ 8U) & ~0x1f03U) | 1U);
        }
        if (request[2] == 1U && request[3] == SNR_QUIET_CONFIRM && snr_cal_state == 0) {
            snr_epoch += 1U;
            memset(snr_noise, 0, sizeof(snr_noise));
            snr_flags = SNR_HAS_HW;
            if (snr_context(snr_cal_context) != 0) snr_flags |= SNR_RF_CHANGED;
            else {
                snr_cal_state = 1; snr_cal_started = now;
                snr_flags |= SNR_CALIBRATING;
                snr_write_control(snr_control & ~1U);
            }
        } else if (request[2] == 2U) {
            snr_cal_state = 0; snr_epoch += 1U; snr_flags = SNR_HAS_HW;
            snr_write_control(((snr_control ^ 8U) & ~0x1f03U) | 1U);
        } else if (request[2] != 0U) {
            response[3] |= SNR_BAD_REQUEST;
        }
        net_snr_poll();
        XTime_GetTime(&now);
        if (snr_context(context) != 0 ||
            ((snr_flags & SNR_NOISE_VALID) && memcmp(context, snr_cal_context, sizeof(context)) != 0)) {
            snr_flags = (snr_flags & ~SNR_NOISE_VALID) | SNR_RF_CHANGED;
        }
        if ((snr_flags & SNR_NOISE_VALID) && net_elapsed_us(snr_cal_finished, now) > 1800000000ULL)
            snr_flags = (snr_flags & ~SNR_NOISE_VALID) | SNR_CAL_EXPIRED;
        if (snr_cal_state == 0 && (Xil_In32(NET_OPENOFDM_RX_REG(6U)) & 3U) != 1U)
            snr_flags = (snr_flags & ~SNR_NOISE_VALID) | SNR_SNAPSHOT_ERROR;
        if (snr_snapshot(&response[16], &seq) != 0) response[3] |= SNR_SNAPSHOT_ERROR;
        response[3] |= snr_flags;
        response[4] = snr_epoch;
        response[5] = snr_cal_finished ? (uint32_t)(net_elapsed_us(snr_cal_finished, now) / 1000ULL) : 0U;
        memcpy(&response[6], context, sizeof(context));
        response[13] = seq;
        memcpy(&response[30], snr_noise, sizeof(snr_noise));
    }
    response[64] = Net_Protocol_Crc32((uint8_t *)response, 256U);
    reply = pbuf_alloc(PBUF_TRANSPORT, sizeof(response), PBUF_RAM);
    if (reply != NULL) {
        if (pbuf_take(reply, response, sizeof(response)) == ERR_OK)
            (void)udp_sendto(udp_control_pcb, reply, addr, port);
        pbuf_free(reply);
    }
    pbuf_free(p);
    return 1;
}
