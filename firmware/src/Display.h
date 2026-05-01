// SSD1306 128x64 wrapper for the Heltec WiFi Kit 32 onboard OLED.
//
// The OLED sits on a separate I2C bus (SDA=GPIO4, SCL=GPIO15, RST=GPIO16),
// so it uses Wire1 — not the GPIB I2C bus on Wire (GPIO21/22).

#pragma once

#include <Adafruit_SSD1306.h>

class Display {
public:
    bool begin();

    void clear();
    void title(const char* t);
    void log(const char* fmt, ...);             // appends one line, scrolls
    void show();                                 // call after multiple log()s

private:
    static constexpr int LINES = 6;
    static constexpr int LINE_LEN = 22;

    Adafruit_SSD1306 oled_{128, 64, &Wire1, -1};
    char title_[LINE_LEN] = {0};
    char buf_[LINES][LINE_LEN] = {{0}};
    int  next_ = 0;
    bool ok_ = false;

    void render_();
};
