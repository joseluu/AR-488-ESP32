

# Hardware Improvements & Known Issues (TODO)

This document tracks identified hardware risks and recommended revisions for the **AR-488-ESP32** project to ensure reliable operation with high-performance laboratory equipment like the **Tektronix TDS 784**.

## 0. Priority
* Use GPIO 17, 18, 19, 23, 25, 26, 27, 2
* map GPIO 5 to a test pin onboard
* add pull-ups to the I2C lines !
* Add a ground testing pin
* Add JTAG connector to use with ESP-PROG - must relocate some IO pins
* reduce board with by 5mm on the right
* increase pin hole diameter by 0.1mm for the 488 connector
* MCP supply doit etre 3.3V, erreur sur les pins du 
* reculer de 3mm le bord du PCB coté prise
* mettre des points de test coté dessous, pin 24 masse et pin 1 data

## 1. Logic Level Protection (Current Limiting)
* **Issue:** The SN7516x transceivers are 5V TTL devices. Their logic "High" output ($V_{OH}$) can exceed 3.6V, which is the absolute maximum rating for the ESP32 GPIOs.
* **Action:** Add **330Ω series resistors** between every ESP32 GPIO and its corresponding SN7516x pin. This protects the ESP32 from overvoltage and limits current through internal ESD protection diodes.

## 2. Boot Strapping Pin Conflicts (Critical)
The ESP32 samples specific pins at power-up to determine its boot mode. If the GPIB bus is active, it can "back-drive" these pins and prevent the ESP32 from starting.
* **GPIO 12 (MTDI):** Must be **LOW** at boot for 3.3V Flash voltage. If High, the ESP32 will boot-loop.
* **GPIO 2:** Must be **LOW** or floating at boot.
* **GPIO 0:** Must be **HIGH** for normal execution (currently safe via pull-up/button).
* **Fix:** Ensure the SN7516x **Enable (EN)** or **Direction (TE/DC)** pins are pulled to a state that keeps the transceiver in **High-Impedance (High-Z)** mode during power-on.

## 3. JTAG / ESP-PROG Compatibility
* **Issue:** The project currently utilizes **GPIO 12, 13, 14, and 15**. These are reserved for the JTAG interface used by the ESP-PROG debugger.
* **Impact:** Real-time hardware debugging is currently impossible while the GPIB interface is connected.
* **Action:** For Revision 2, consider remapping GPIB signals to non-JTAG pins (e.g., GPIOs 16, 17, 18, 19, 21, 22, 23, 25, 26, 27) to allow for simultaneous debugging.

## 4. Power & Decoupling
* **Action:** Ensure **0.1µF ceramic decoupling capacitors** are placed physically adjacent to the $V_{CC}$ pins of both the SN75160 and SN75161.
* **Action:** Tie the **GPIB Shield (Pin 12)** to the PCB digital ground to improve signal integrity during high-speed waveform transfers from the TDS 784.



## 5. Software-Side Initialization
* **Action:** The firmware `setup()` function must immediately set the Transceiver Control pins (TE/DC) to a "Listen" or "High-Z" state to release the strapping pins as quickly as possible after power-up.

## 6. Default-Safe State for SN75161B Direction Inputs
* **Issue:** `TE_CTRL` and `DC` on the SN75161B are driven by the MCP23017. After power-on reset (or any time the MCP23017 is reset or its pins are configured as inputs), the MCP23017 outputs go high-Z and these SN75161B inputs float, leaving the transceiver direction undefined and potentially driving the GPIB bus while the ESP32 is still booting.
* **Action:** Add external pull resistors (10 kΩ) on `TE_CTRL` and `DC` to define a safe default direction (Listen / device) that keeps the bus side high-Z until firmware takes over. With those pulls in place, deliberately tri-stating the MCP outputs (set `IODIRA` bits to 1) becomes a safe "release the bus" operation.