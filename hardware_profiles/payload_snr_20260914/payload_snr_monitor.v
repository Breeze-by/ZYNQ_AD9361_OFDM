// Passive, unscaled time-domain I/Q power monitor. No decoder feedback.
// control: bit0 enable, bit1 explicit quiet calibration, bit2 snapshot toggle,
// bit3 clear toggle, bits[12:8] snapshot word selector. All at RX AXI clock.
// Noise comes from the input of the sync_long sample RAM; payload comes from
// that RAM's exact read samples BEFORE CFO rotation, FFT and UEP restoration.
`timescale 1ns/1ps
module payload_snr_monitor (
    input clock, input reset,
    input [31:0] control, input [31:0] phy_config,
    input [31:0] noise_iq, input noise_strobe,
    input [31:0] payload_iq, input payload_strobe,
    input valid_header,
    output reg [31:0] snapshot_seq,
    output reg [31:0] read_data
);
    reg clear_seen, snapshot_seen;
    reg [63:0] cycles, count, power_sum;
    reg signed [63:0] i_sum, q_sum;
    reg [31:0] clips, headers;
    reg [31:0] snapshot [0:13];
    reg signed [15:0] in_i, in_q, i_d1, q_d1, i_d2, q_d2;
    reg [31:0] i_square, q_square;
    reg [32:0] power_d2;
    reg valid_d0, valid_d1, valid_d2, clip_d1, clip_d2;
    wire [31:0] selected_iq = control[1] ? noise_iq : payload_iq;
    wire selected_valid = control[0] && (control[1] ? noise_strobe : payload_strobe);
    integer k;

    // Registered multiplier and adder keep arithmetic off the receive path.
    always @(posedge clock) begin
        if (reset || control[3] != clear_seen) begin
            valid_d0 <= 0; valid_d1 <= 0; valid_d2 <= 0;
            in_i <= 0; in_q <= 0; i_d1 <= 0; q_d1 <= 0; i_d2 <= 0; q_d2 <= 0;
            i_square <= 0; q_square <= 0; power_d2 <= 0;
            clip_d1 <= 0; clip_d2 <= 0;
        end else begin
            valid_d0 <= selected_valid;
            in_i <= selected_iq[31:16]; in_q <= selected_iq[15:0];
            valid_d1 <= valid_d0;
            i_square <= in_i * in_i; q_square <= in_q * in_q;
            i_d1 <= in_i; q_d1 <= in_q;
            clip_d1 <= (in_i >= 32760 || in_i <= -32760 || in_q >= 32760 || in_q <= -32760);
            valid_d2 <= valid_d1;
            power_d2 <= {1'b0, i_square} + {1'b0, q_square};
            i_d2 <= i_d1; q_d2 <= q_d1; clip_d2 <= clip_d1;
        end
    end

    always @(posedge clock) begin
        if (reset) begin
            cycles <= 0; count <= 0; power_sum <= 0; i_sum <= 0; q_sum <= 0;
            clips <= 0; headers <= 0; clear_seen <= 0; snapshot_seen <= 0;
            snapshot_seq <= 0;
            for (k=0; k<14; k=k+1) snapshot[k] <= 0;
        end else begin
            cycles <= cycles + 1'b1;
            clear_seen <= control[3];
            snapshot_seen <= control[2];
            if (control[3] != clear_seen) begin
                count <= 0; power_sum <= 0; i_sum <= 0; q_sum <= 0;
                clips <= 0; headers <= 0;
            end else begin
                if (valid_d2) begin
                    count <= count + 1'b1;
                    power_sum <= power_sum + {31'd0, power_d2};
                    i_sum <= i_sum + {{48{i_d2[15]}}, i_d2};
                    q_sum <= q_sum + {{48{q_d2[15]}}, q_d2};
                    if (clip_d2) clips <= clips + 1'b1;
                end
                if (control[0] && valid_header) headers <= headers + 1'b1;
            end
            // Atomic multiword snapshot; selector changes do NOT resnapshot.
            if (control[2] != snapshot_seen) begin
                snapshot_seq <= snapshot_seq + 1'b1;
                snapshot[0] <= count[31:0]; snapshot[1] <= count[63:32];
                snapshot[2] <= power_sum[31:0]; snapshot[3] <= power_sum[63:32];
                snapshot[4] <= i_sum[31:0]; snapshot[5] <= i_sum[63:32];
                snapshot[6] <= q_sum[31:0]; snapshot[7] <= q_sum[63:32];
                snapshot[8] <= clips; snapshot[9] <= headers;
                snapshot[10] <= phy_config; snapshot[11] <= control & 32'hf;
                snapshot[12] <= cycles[31:0]; snapshot[13] <= cycles[63:32];
            end
        end
    end
    always @* begin
        read_data = 0;
        if (control[12:8] < 14) read_data = snapshot[control[12:8]];
    end
endmodule
