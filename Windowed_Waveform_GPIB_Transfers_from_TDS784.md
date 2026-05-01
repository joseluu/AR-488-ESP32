

# Windowed waveform transfers on a TDS784A

# 1. Requesting a Sub-Window for Data Transfer

If you have already performed a large acquisition (e.g., 500,000 points) and only want to transfer a specific portion of that data over GPIB, you can define a **transfer window** using the following commands:

- ***DATa:STARt \<NR1\>: This command specifies the first data point in the waveform record to be transferred.**

- ***DATa:STOP \<NR1\>: This command specifies the last data point in the waveform record for the transfer.**

- ***DATa:SNAp: This is a shortcut command that automatically sets the `DATa:STARt` and `DATa:STOP` values to match the current positions of the vertical bar cursors on the oscilloscope screen.**

By setting these values, a subsequent **CURVe?** query will only return the points within that specific window, which is much faster and more efficient than transferring the entire 500,000-point record.

# 2. Changing the Acquisition Record Length

If your goal is to reduce the actual number of points the instrument acquires in the first place, you can use the horizontal commands to change the **Record Length**:

- ***HORizontal:RECOrdlength \<NR1\>: This command sets the number of points that make up the waveform record.**

- ***Available lengths typically include 500, 1,000, 2,500, 5,000, and 15,000 points as standard.**

- ***With Option 1M, the TDS 700A models support extended lengths of 50,000, 75,000, 100,000, 130,000, 250,000, and 500,000 points.**

Important Considerations for Large Records

- ***Memory Allocation: Before you can store or transfer very large waveforms into reference memory, you must ensure memory is allocated using the ALLOcate:WAVEform:REF\<x\> command.**

- ***Data Format: When transferring large amounts of data, using Binary formats (specified via `DATa:ENCdg`) is recommended over ASCII to increase transmission speeds and reduce the number of bytes sent.**

- ***Hi Res Mode: Note that in Hi Res acquisition mode, the maximum available record length is reduced (e.g., to 50,000 points even with Option 1M) because this mode requires twice the acquisition memory.**

