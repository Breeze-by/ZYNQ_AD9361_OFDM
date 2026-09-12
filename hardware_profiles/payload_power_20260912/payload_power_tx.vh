// Diagnostic-only unequal-power transmission. Legacy BPSK 1/2 only.
// TX reg2: [31:24]=A7, [18:16]=right shift (0..4), [13:8]=protected
// DATA symbols (0..63), [6:0]=existing data scrambler seed. Write when idle.
wire [15:0] result_i_unscaled;
wire [15:0] result_q_unscaled;
reg [31:0] uep_cfg;
reg [6:0] uep_sample;
reg [11:0] uep_data_symbol;
wire uep_active = uep_cfg[31:24] == 8'ha7 &&
                  uep_cfg[18:16] <= 4 && PKT_TYPE == LEGACY &&
                  RATE == 5'b01011 && state3 == S3_DATA &&
                  uep_data_symbol >= {6'd0, uep_cfg[13:8]};

always @(posedge clk) begin
    if (reset_int) begin
        uep_cfg <= 0;
        uep_sample <= 0;
        uep_data_symbol <= 0;
    end else begin
        if (state3 == S3_WAIT_PKT && phy_tx_start && result_iq_ready)
            uep_cfg <= payload_power_config;
        if (state3 != S3_DATA) begin
            uep_sample <= 0;
            uep_data_symbol <= 0;
        end else if (result_iq_ready && result_iq_valid) begin
            if (uep_sample == 79) begin
                uep_sample <= 0;
                if (uep_data_symbol != 12'hfff)
                    uep_data_symbol <= uep_data_symbol + 1'b1;
            end else uep_sample <= uep_sample + 1'b1;
        end
    end
end

// Symmetric nearest rounding with ties away from zero. Fixed shift choices
// use one increment rather than magnitude/negate/add/negate carry chains.
function [15:0] uep_attenuate;
    input signed [15:0] value;
    input [2:0] amount;
    begin
        case (amount)
            1: uep_attenuate = {{1{value[15]}},value[15:1]} + (value[0] & ~value[15]);
            2: uep_attenuate = {{2{value[15]}},value[15:2]} + (value[1] & (|value[0:0] | ~value[15]));
            3: uep_attenuate = {{3{value[15]}},value[15:3]} + (value[2] & (|value[1:0] | ~value[15]));
            4: uep_attenuate = {{4{value[15]}},value[15:4]} + (value[3] & (|value[2:0] | ~value[15]));
            default: uep_attenuate = value;
        endcase
    end
endfunction

// Preamble ROM outputs must bypass the arithmetic altogether. The scaling
// input is the DATA/SIGNAL FIFO path, selected only during unprotected DATA.
wire [15:0] uep_fifo_i = fifo_turn == PKT_FIFO ? pkt_fifo_odata[31:16] : CP_fifo_odata[31:16];
wire [15:0] uep_fifo_q = fifo_turn == PKT_FIFO ? pkt_fifo_odata[15:0] : CP_fifo_odata[15:0];
assign result_i = uep_active ? uep_attenuate(uep_fifo_i, uep_cfg[18:16]) : result_i_unscaled;
assign result_q = uep_active ? uep_attenuate(uep_fifo_q, uep_cfg[18:16]) : result_q_unscaled;
