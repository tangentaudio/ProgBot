#define IO_RELAY_PWR 7
#define IO_RELAY_LOGIC 8
#define IO_GND_DETECT 12
#define IO_DETECT_LED 11

void setup() {
  // put your setup code here, to run once:

  pinMode(IO_RELAY_PWR, OUTPUT);
  pinMode(IO_RELAY_LOGIC, OUTPUT);
  pinMode(LED_BUILTIN, OUTPUT);
  pinMode(IO_GND_DETECT, INPUT_PULLUP);
  pinMode(IO_DETECT_LED, OUTPUT);

  Serial.begin(9600); // Start serial communication
}

void loop() {
  static char command[32]; 
  static uint8_t commandIndex = 0;  
  static uint8_t counter = 0;
  static bool flip = false;

  digitalWrite(IO_DETECT_LED, digitalRead(IO_GND_DETECT));


  if (counter++ > 100) {
    counter = 0;
    flip = !flip;

    digitalWrite(LED_BUILTIN, flip);
  }
  delay(10);
  
  while (Serial.available() > 0) {
    char incomingChar = Serial.read();

    if (incomingChar == '\n' || incomingChar == '\r') { // Command is terminated by newline or carriage return
      command[commandIndex] = '\0'; // Null-terminate the string

      // Process the received command
      if (strcmp(command, "PowerOn") == 0) {
        digitalWrite(IO_RELAY_PWR, HIGH);
        Serial.println("OK PowerOn");
      } else if (strcmp(command, "PowerOff") == 0) {
        digitalWrite(IO_RELAY_PWR, LOW);
        Serial.println("OK PowerOff");
      } else if (strcmp(command, "LogicOn") == 0) {
        digitalWrite(IO_RELAY_LOGIC, HIGH);
        Serial.println("OK LogicOn");
      } else if (strcmp(command, "LogicOff") == 0) {
        digitalWrite(IO_RELAY_LOGIC, LOW);
        Serial.println("OK LogicOff");
      } else if (strcmp(command, "AllOn") == 0) {
        digitalWrite(IO_RELAY_PWR, HIGH);
        digitalWrite(IO_RELAY_LOGIC, HIGH);
        Serial.println("OK AllOn");
      } else if (strcmp(command, "AllOff") == 0) {
        digitalWrite(IO_RELAY_PWR, LOW);
        digitalWrite(IO_RELAY_LOGIC, LOW);
        Serial.println("OK AllOff");
      } else if (strcmp(command, "Stat") == 0) {
        if (digitalRead(IO_GND_DETECT)) {
          Serial.println("CONTACT NOT FOUND");
        } else {
          Serial.println("CONTACT PRESENT");
        }
      } else {
        Serial.println("ERROR");
      }

      // Reset command buffer
      commandIndex = 0;
      memset(command, 0, sizeof(command));
    } else {
      // Add character to buffer if space is available
      if (commandIndex < sizeof(command) - 1) {
        command[commandIndex++] = incomingChar;
      }
    }
  }
}
