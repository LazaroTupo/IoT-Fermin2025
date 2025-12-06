#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <WiFi.h>
#include <HTTPClient.h>

// Configuración WiFi
const char* ssid = "GABRIEL";
const char* password = "U17207627@";
const char* serverURL = "http://192.168.100.20:5000/get_car_status";

LiquidCrystal_I2C lcd = LiquidCrystal_I2C(0x27, 16, 2);

int pinZumbador = 4;
int frec = 2000;
int led = 14;
int distancia = 0;
int pinEcho = 12;
int pinTrig = 13;

bool carDetectedByCamera = false;
unsigned long lastCheckTime = 0;
const unsigned long checkInterval = 1000; // Verificar cada 1 segundo

long readUltrasonicDistance(int triggerPin, int echoPin) {
  digitalWrite(triggerPin, LOW);
  delayMicroseconds(2);
  digitalWrite(triggerPin, HIGH);
  delayMicroseconds(10);
  digitalWrite(triggerPin, LOW);
  
  long duration = pulseIn(echoPin, HIGH, 30000);
  return duration;
}

void checkCameraDetection() {
  if (WiFi.status() == WL_CONNECTED) {
    HTTPClient http;
    http.begin(serverURL);
    http.setTimeout(3000);
    
    int httpCode = http.GET();
    
    if (httpCode == 200) {
      String payload = http.getString();
      
      // Buscar "car_detected":true o false
      if (payload.indexOf("\"car_detected\": true") > 0 || 
          payload.indexOf("\"car_detected\":true") > 0) {
        carDetectedByCamera = true;
        Serial.println("✅ CÁMARA: Vehículo detectado");
      } else {
        carDetectedByCamera = false;
        Serial.println("ℹ️  CÁMARA: Sin vehículo");
      }
    } else {
      Serial.printf("⚠️  Error HTTP: %d\n", httpCode);
    }
    
    http.end();
  } else {
    Serial.println("⚠️  WiFi desconectado");
  }
}

void setup() {
  Serial.begin(115200);
  
  // Configurar pines
  ledcAttach(pinZumbador, frec, 8);
  pinMode(led, OUTPUT);
  pinMode(pinTrig, OUTPUT);
  pinMode(pinEcho, INPUT);
  
  // Inicializar LCD
  lcd.init();
  lcd.backlight();
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("Conectando WiFi");
  
  // Conectar WiFi
  WiFi.begin(ssid, password);
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 20) {
    delay(500);
    Serial.print(".");
    attempts++;
  }
  
  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\n✅ WiFi conectado");
    Serial.print("📍 IP: ");
    Serial.println(WiFi.localIP());
    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print("WiFi OK");
    lcd.setCursor(0, 1);
    lcd.print(WiFi.localIP());
    delay(2000);
  } else {
    Serial.println("\n❌ WiFi no conectado");
    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print("WiFi ERROR");
  }
  
  Serial.println("═══════════════════════════════════════");
  Serial.println("   Sistema de Estacionamiento ESP32");
  Serial.println("═══════════════════════════════════════");
}

void loop() {
  unsigned long currentTime = millis();
  
  // Verificar detección de cámara cada segundo
  if (currentTime - lastCheckTime >= checkInterval) {
    lastCheckTime = currentTime;
    checkCameraDetection();
  }
  
  // Solo ejecutar sensor ultrasónico si la cámara detectó un carro
  if (carDetectedByCamera) {
    long duration = readUltrasonicDistance(pinTrig, pinEcho);
    
    // Calcular distancia en centímetros
    if (duration > 0) {
      distancia = duration * 0.0343 / 2;
    } else {
      distancia = 0;
    }

    if (distancia <= 5 && distancia > 0) {
      // Objeto sobre el sensor - ESTACIONADO
      ledcWriteTone(pinZumbador, 2000);
      
      lcd.clear();
      lcd.setCursor(0, 0);
      lcd.print("** AUTOMOVIL **");
      lcd.setCursor(0, 1);
      lcd.print("** ESTACIONADO **");
      
      digitalWrite(led, LOW);
      distancia = 0;
      
      Serial.println("═══════════════════════════════════════");
      Serial.println("🚗 VEHÍCULO ESTACIONADO");
      Serial.println("📍 Objeto detectado sobre el sensor");
      Serial.println("═══════════════════════════════════════");
      
    } else {
      // Espacio ocupado pero vehículo no totalmente estacionado
      ledcWriteTone(pinZumbador, 0);
      digitalWrite(led, HIGH);
    
      lcd.clear();
      lcd.setCursor(0, 0);
      lcd.print("ESPACIO OCUPADO");
      lcd.setCursor(0, 1);
      lcd.print("Dist: ");
      lcd.print(distancia);
      lcd.print(" cm");
      
      Serial.print("ℹ️  Espacio ocupado - Distancia: ");
      Serial.print(distancia);
      Serial.println(" cm");
    }
    
  } else {
    // No hay carro detectado por la cámara
    ledcWriteTone(pinZumbador, 0);
    digitalWrite(led, HIGH);
    
    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print("ESTACIONAMIENTO");
    lcd.setCursor(0, 1);
    lcd.print("*** LIBRE ***");
    
    // Solo imprimir cada 5 segundos para no saturar el serial
    if (currentTime % 5000 < 200) {
      Serial.println("✓ Estacionamiento libre");
    }
  }
  
  delay(200);
}