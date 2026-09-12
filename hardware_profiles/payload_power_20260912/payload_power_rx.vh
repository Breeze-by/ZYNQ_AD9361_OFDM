// RX reg5: [31:24]=A7, [18:16]=matching TX shift (0..4), [15:10]=protected
// DATA symbols. Low [9:0] retain original watchdog/FFT-window configuration.
// Counter includes SIGNAL as symbol 1; first DATA is symbol 2.
reg [11:0] uep_eq_symbol;
reg [31:0] uep_rx_cfg;
wire uep_compensate = uep_rx_cfg[31:24] == 8'ha7 &&
                      uep_rx_cfg[18:16] > 0 && uep_rx_cfg[18:16] <= 4 &&
                      payload_power_legacy_bpsk && !ht &&
                      uep_eq_symbol >= ({6'd0, uep_rx_cfg[15:10]} + 12'd2);
always @(posedge clock) begin
    if (reset | reset_internal) begin
        uep_eq_symbol <= 0;
        uep_rx_cfg <= 0;
        payload_power_shift_out <= 0;
    end else if (enable) begin
        if (state == S_FIRST_LTS) uep_rx_cfg <= payload_power_config;
        if (state == S_GET_POLARITY && uep_eq_symbol != 12'hfff)
            uep_eq_symbol <= uep_eq_symbol + 1'b1;
        if (state == S_ALL_SC_PE_CORRECTION && norm_out_stb && data_subcarrier_mask[0])
            payload_power_shift_out <= uep_compensate ? uep_rx_cfg[18:16] : 3'd0;
    end
end

// Restore known constellation scale, not SNR. Expand before shifting and
// saturate instead of wrapping; bypass is exactly the original expression.
function [15:0] uep_restore;
    input signed [31:0] value;
    input [2:0] amount;
    reg signed [39:0] wide;
    begin
        wide = $signed({{8{value[31]}}, value}) <<< amount;
        if (wide > 40'sd32767) uep_restore = 16'h7fff;
        else if (wide < -40'sd32768) uep_restore = 16'h8000;
        else uep_restore = wide[15:0];
    end
endfunction
wire [31:0] uep_normalized = uep_compensate ?
    {uep_restore(norm_i, uep_rx_cfg[18:16]), uep_restore(norm_q, uep_rx_cfg[18:16])} :
    {norm_i[31], norm_i[14:0], norm_q[31], norm_q[14:0]};
