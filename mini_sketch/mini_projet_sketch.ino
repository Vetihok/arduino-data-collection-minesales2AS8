#include <Arduino_LSM9DS1.h>
#include <SPI.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <limits.h>

// ------------ OUTPUT SETUP ------------
#define SCREEN_WIDTH 128 // OLED display width, in pixels
#define SCREEN_HEIGHT 64 // OLED display height, in pixels

// Declaration for an SSD1306 display connected to I2C (SDA, SCL pins)
// The pins for I2C are defined by the Wire-library. 
// On an arduino UNO:       A4(SDA), A5(SCL)
// On an arduino MEGA 2560: 20(SDA), 21(SCL)
// On an arduino LEONARDO:   2(SDA),  3(SCL), ...
#define OLED_RESET     -1 // Reset pin # (or -1 if sharing Arduino reset pin)
#define SCREEN_ADDRESS 0x3C
Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);
const int BLUE_LED = D11;
const int BUZZER = A6;
const unsigned long BAUD = 9600;

// ------------ CONFIG ------------
const unsigned long SAMPLE_PERIOD_MS = 100;  // 10 Hz
const unsigned int MAX_DLT_SAMPLES = 10;     // Number of DLT samples before sending a frame in KF mode
const unsigned int DLT_THRESHOLD = 128;       // Absolute delta threshold above which a frame in KF mode is sent

const unsigned int STORED_SAMPLES = 50;      // maximum number of samples in the ring buffer

// ------------ UTILITIES ------------
int buffer[50][4];                           // ring buffer
unsigned int buf_index = 0, buf_count = 0;

bool logging = false;                        // set by START/STOP commands from PC
bool compression = false;                    // set by MODE=DLT/MODE=KF commands from PC
String commandBuffer = "";                   // to accumulate incoming serial commands

unsigned long lastSampleTime = 0;
unsigned long seq = 0, last_kf_seq = 0; // last_kf_seq keep the last seq of the last frame sent in KF mode
int last_ax = 0, last_ay = 0, last_az = 0;

void setup() {

  pinMode(BUZZER, OUTPUT);
  pinMode(BLUE_LED, OUTPUT);

  Serial.begin(BAUD);

  // Wait for display
  delay(500);

  // SSD1306_SWITCHCAPVCC = generate display voltage from 3.3V internally
  if(!display.begin(SSD1306_SWITCHCAPVCC, SCREEN_ADDRESS)) {
    Serial.println(F("SSD1306 allocation failed"));
    for(;;); // Don't proceed, loop forever
  }

  // Show initial display buffer contents on the screen --
  // the library initializes this with an Adafruit splash screen.
  display.display();
  delay(2000); // Pause for 2 seconds

  // Clear the buffer
  display.clearDisplay();

  if (!IMU.begin()) {
    Serial.println("IMU init failed");
    while (1) {
    }
  }

  Serial.println("IMU ready. Waiting for START / STOP commands.");
}

// compute the checksum of a given sample
static uint8_t xorChecksum(const char* s) {
  uint8_t x = 0;
  while (*s) x ^= (uint8_t)(*s++);
  return x;
}

// play a note on the buzzer
void play(int freq, int duration) {
  tone(BUZZER, freq, duration);
  delay(duration * 1.3);
  noTone(BUZZER);
}

// send the stats of the 
void requestStats(unsigned long int now, int n_samples) {
  char body[150];
  snprintf(body, sizeof(body), "%lu,%lu,RAW,cmd=STATS,count=%d,ax_mean=%.2f,ax_min=%d,ax_max=%d,ay_mean=%.2f,ay_min=%d,ay_max=%d,az_mean=%.2f,az_min=%d,az_max=%d",
           seq++, now, n_samples, mean_of_col(0, n_samples), min_of_col(0, n_samples), max_of_col(0, n_samples), 
                                  mean_of_col(1, n_samples), min_of_col(1, n_samples), max_of_col(1, n_samples), 
                                  mean_of_col(2, n_samples), min_of_col(2, n_samples), max_of_col(2, n_samples));    
  
  uint8_t cs = xorChecksum(body);

  Serial.print('@');
  Serial.print(body);
  Serial.print('*');
  if (cs < 16) Serial.print('0');
  Serial.print(cs, HEX);
  Serial.print('\n');
}

// handle Serial commands
void handleSerialCommands(unsigned long int now) {
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n' || c == '\r') {
      if (commandBuffer.length() > 0) {
        String cmd = commandBuffer;
        commandBuffer = "";

        // Detect if the command ends with an int
        const char *ptr = cmd.c_str();
        while (*ptr && !isdigit(*ptr)) {
          ptr++;
        }
        int n_samples = (int)strtol(ptr, NULL, 10);

        cmd.trim();
        cmd.toUpperCase();

        if (cmd == "START" || cmd == "TART") {
          logging = true;
          digitalWrite(BLUE_LED, HIGH);
          play(392, 500);
          Serial.println("ACK:START");
        } else if (cmd == "STOP") {
          logging = false;
          digitalWrite(BLUE_LED, LOW);
          play(392, 500);
          play(261, 500);
          Serial.println("ACK:STOP");
        } else if (cmd == "MODE=DLT") {
          compression = true;
          Serial.println("ACK:MODE=DLT");
        } else if (cmd == "MODE=KF") {
          compression = false;
          Serial.println("ACK:MODE=KF");
        } else if (cmd.startsWith("STATS") && n_samples > 0) {
          Serial.print("ACK:STATS");
          Serial.println(n_samples);
          if (n_samples <= buf_count)
            requestStats(now, n_samples);
          else
            requestStats(now, buf_count);
        } else if (cmd == "STATS") {
          Serial.println("ACK:STATS");
          requestStats(now, buf_count);
        } else {
          Serial.print("ERR:UNKNOWN_CMD ");
          Serial.println(cmd);
        }
      }
    } else {
      commandBuffer += c;
      if (commandBuffer.length() > 50) {
        commandBuffer = "";
      }
    }
  }
}

// update the screen display
void updateScreen() {
  display.clearDisplay();

  display.setTextSize(2);             // Draw 2X-scale text
  display.setCursor(0,0);             // Start at top-left corner
  display.setTextColor(SSD1306_WHITE);

  if (logging) {
    display.print("LOG ");
    if (compression)
      display.println("DLT");
    else
      display.println("KF");

    display.setTextSize(1);
    display.print("ax = ");
    display.println(last_ax);
    display.print("ay = ");
    display.println(last_ay);
    display.print("az = ");
    display.println(last_az);
  } else {
    display.print("IDLE ");
    if (compression)
      display.println("DLT");
    else
      display.println("KF");
  }

  display.display();
}

// return the minimum of one of the buffer column
int min_of_col(int col, int bound) {
  int min = INT_MAX;
  for (int i = 0; i < bound; i++) {
    if (buffer[i][col] < min) min = buffer[i][col];
  }
  return min;
}

// return the maximum of one of the buffer column
int max_of_col(int col, int bound) {
  int max = 0;
  for (int i = 0; i < bound; i++) {
    if (buffer[i][col] > max) max = buffer[i][col];
  }
  return max;
}

// return the mean of one of the buffer column
float mean_of_col(int col, int bound) {
  float sum = 0;
  for (int i = 0; i < bound; i++) {
    sum += (float)buffer[i][col];
  }
  return sum/bound;
}

// send the data with serial through a special format
void sendIMUSample(unsigned long now) {
  if (!IMU.accelerationAvailable()) return;
  float ax_g, ay_g, az_g;
  IMU.readAcceleration(ax_g, ay_g, az_g);

  int ax = (int)lround(ax_g * 1000.0f);  // g -> mg
  int ay = (int)lround(ay_g * 1000.0f);
  int az = (int)lround(az_g * 1000.0f);

  buffer[buf_index][0] = ax;
  buffer[buf_index][1] = ay;
  buffer[buf_index][2] = az;
  buffer[buf_index][3] = now;

  buf_index++;
  buf_index = buf_index % STORED_SAMPLES;
  if (buf_count < STORED_SAMPLES) buf_count++;
  
  int max_delta = max(abs(ax - last_ax), max(abs(ay - last_ay), abs(az - last_az)));
  char body[96];
  if (!compression || (seq - last_kf_seq) >= MAX_DLT_SAMPLES || max_delta > DLT_THRESHOLD) {
    snprintf(body, sizeof(body), "%lu,%lu,KF,mode=LOGGING,ax=%d,ay=%d,az=%d",
           seq++, now, ax, ay, az);
    last_kf_seq = seq;
  } else {
    int dax = ax - last_ax, day = ay - last_ay, daz = az - last_az;
    snprintf(body, sizeof(body), "%lu,%lu,DLT,mode=LOGGING,dax=%d,day=%d,daz=%d",
           seq++, now, dax, day, daz);
  }

  last_ax = ax;
  last_ay = ay;
  last_az = az;
  uint8_t cs = xorChecksum(body);

  Serial.print('@');
  Serial.print(body);
  Serial.print('*');
  if (cs < 16) Serial.print('0');
  Serial.print(cs, HEX);
  Serial.print('\n');
}

void loop() {
  unsigned long now = millis();
  updateScreen();
  handleSerialCommands(now);
  if (!logging) {
    return;
  }

  if (now - lastSampleTime >= SAMPLE_PERIOD_MS) {
    lastSampleTime = now;
    sendIMUSample(now);
  }
}
