MCP tools for TDS784A measurements


# 1. Measurement Tools

These tools allow the AI to directly retrieve numerical data and calculated waveform parameters.

- ***get\_measurement: Retrieves a specific automated measurement (e.g., Frequency, Rise Time, Pk-Pk) from a selected channel. The instrument supports 25 different automatic measurements.**

- ***get\_measurement\_snapshot: Performs a one-time capture of all 25 single-waveform measurements for the currently selected channel and returns them as a single block of data.**

- ***setup\_measurement: Configures one of the four available on-screen measurement slots, defining the source channel and the measurement type.**

- ***set\_measurement\_ref\_levels: Sets the high, middle, and low reference levels (in percent or absolute units) used for timing and amplitude calculations.**

- ***set\_measurement\_gating: Limits automated measurements to a specific portion of the waveform record defined by vertical cursors.**

# 2. Acquisition & Control Tools

These tools manage how the instrument captures the signal before a measurement is taken.

- ***autoset: Automatically adjusts the vertical, horizontal, and trigger controls to produce a stable, usable display of the input signal.**

- ***set\_acquisition\_mode: Sets the mode to Sample, Peak Detect, Hi Res, Envelope, or Average.**

- ***set\_acquisition\_state: Starts or stops the acquisition system (equivalent to the RUN/STOP button).**

- ***set\_stop\_after: Configures the scope to stop after a single acquisition sequence or when a limit test condition is met.**

# 3. Waveform Data Tools

For advanced AI analysis, the raw digitized points must be accessible.

- ***get\_waveform\_curve: Transfers the raw data points of a waveform record from the oscilloscope to the AI for external processing or storage.**

- ***get\_waveform\_preamble: Retrieves the vertical and horizontal scaling factors necessary to convert raw digitized "counts" into actual voltage and time values.**

# 4. Vertical & Horizontal Setup Tools

These tools allow the AI to "zoom in" or "zoom out" to ensure signals are not clipped and have sufficient resolution for accurate measurement.

- ***set\_vertical\_channel: Sets the volts/division, vertical offset, coupling (AC/DC/GND), and bandwidth limit for a specific channel.**

- ***set\_horizontal\_scale: Adjusts the time/division and the horizontal position of the trigger point within the record.**

- ***set\_trigger: Configures the trigger type (Edge, Logic, Pulse), source, coupling, and level to stabilize the signal.**


# 5. Instrument State Management

## 1. Tool: **`capture\_complete\_setup`**

This tool retrieves the full instrument configuration to be stored by the AI in its long-term memory or a database.

- ***Logic: Execute the `SET?` query.**

- ***Source Requirement: Ensure `HEADer` is set to ON before the query so the response is formatted as a valid set command.**

- ***Output: A comprehensive ASCII string containing all vertical, horizontal, trigger, and display settings.**

- ***AI Context: The AI should save this string alongside the measurement results. This is more robust than saving individual parameters because it captures hidden states and internal offsets.**

## 2. Tool: **`restore\_complete\_setup`**

This tool takes a previously saved state string and re-programs the instrument.

- ***Arguments: `setup\_string` (The string retrieved from `capture\_complete\_setup`).**

- ***Logic: Transmit the string directly to the instrument via the GPIB/Server interface.**

- ***Post-Condition Check:**

  - ***Use the \*OPC? (Operation Complete) query to ensure the instrument has finished processing the large configuration block before attempting further measurements.**

  - ***Query BUSY? to ensure the instrument is ready for the next command.**

## 3. Tool: **`manage\_internal\_slots`**

The instrument provides ten internal non-volatile RAM (NVRAM) locations for saving and recalling setups without transferring data to a controller.

- ***Arguments:**

  - ***`action`: (Choice of `SAVE` or `RECALL`).**

  - ***`slot\_number`: (Integer 1–10).**

- ***Commands:**

  - ***\*SAV \<NR1\>: Saves the current setup to the specified internal location.**

  - ***\*RCL \<NR1\>: Recalls the setup from the specified internal location.**

- ***Recommendation: The AI should use these for quick toggling during a single active session, while using the `SET?` string for long-term "later session" persistence.**

## 4. Tool: **`verify\_instrument\_identity`**

Before restoring a setup, the AI must verify that the hardware matches the saved state to prevent compatibility errors (e.g., restoring a TDS 784A setup onto a TDS 684A).

- ***Logic: Execute the \*IDN? query.**

- ***Validation: The AI should compare the model number and firmware version in the saved metadata against the current `\*IDN?` response.**

## 5. Tool: **`reset\_to\_baseline`**

To ensure a "clean slate" before applying a complex saved setup, the AI should be able to return the device to a known state.

- ***Logic:**

  - ***FACtory: Resets the instrument to the factory default settings.**

  - ***\*RST: Executes a standard IEEE 488.2 reset.**

- ***Use Case: Always execute a reset before restoring a saved setup string to prevent legacy settings from interfering with the restored state.**

Summary Specification for the MCP Server

| MCP Tool Name | GPIB Commands Used | Purpose |
| :-: | :-: | :-: |
| **`get\_setup\_state`** | **`HEADer ON; SET?`** | Captures every parameter for external storage. |
| **`set\_setup\_state`** | **`\<string\>`** | Sends a captured state back to the instrument. |
| **`save\_internal`** | **`\*SAV \<1-10\>`** | Stores setup in the oscilloscope's NVRAM. |
| **`recall\_internal`** | **`\*RCL \<1-10\>`** | Quickly restores setup from NVRAM. |
| **`factory\_reset`** | **`FACtory`** | Clears all custom settings to default. |
| **`sync\_check`** | **`\*OPC?; BUSY?`** | Ensures state restoration is complete before proceeding. |

**Implementation Note for the AI**: When restoring a state, the AI should be programmed to check for **Service Requests (SRQs)** or error codes in the \**Standard Event Status Register (* to confirm that the setup was accepted without syntax or execution errors

  


