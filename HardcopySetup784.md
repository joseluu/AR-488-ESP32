- ***Hardcopy setup**

  - ***HARDCopy:POrt GPIB: Sets the output destination to the communication bus.**

  - ***HARDCopy:FORMat \<format\>: Selects the image file type. Supported bitmap-compatible formats typically include BMP, PCX, and TIFF.**

  - ***HARDCopy:LAYout \<orientation\>: Configures the image for PORTrait or LANDscape orientation.**

  - ***HARDCopy:PALette \<type\>: (Optional) Selects the color or hardcopy-specific palette to be used in the image.**

- ***Execution and Synchronization:**

  - ***HARDCopy STARt: Initiates the conversion of the current screen display into the selected format and begins transmission.**

  - ***Status Monitoring: The instrument will return a 1 (Busy) response to the BUSY? query while the hardcopy is being generated and transmitted. The AI must wait for `BUSY?` to return `0` before attempting further commands.**

