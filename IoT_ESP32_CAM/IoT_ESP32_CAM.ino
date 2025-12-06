#include "esp_camera.h"
#include <WiFi.h>
#include <HTTPClient.h>

// ===========================
// WiFi Configuration
// ===========================
const char *ssid = "GABRIEL";
const char *password = "U17207627@";

// ===========================
// Server Configuration
// ===========================
const char *serverURL = "http://192.168.100.20:5000/detect"; // Cambia la IP por la de tu servidor
const unsigned long sendInterval = 500; // Enviar cada 500ms (2 FPS)

// ===========================
// Camera Configuration
// ===========================
#define CAMERA_MODEL_AI_THINKER
#include "camera_pins.h"

// ===========================
// Variables Globales
// ===========================
unsigned long lastSendTime = 0;
unsigned long frameCount = 0;
unsigned long successCount = 0;
unsigned long errorCount = 0;

// ===========================
// Setup Camera
// ===========================
bool setupCamera() {
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sccb_sda = SIOD_GPIO_NUM;
  config.pin_sccb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;
  config.grab_mode = CAMERA_GRAB_LATEST;
  config.fb_location = CAMERA_FB_IN_PSRAM;
  config.jpeg_quality = 12; // Calidad JPEG (10-63, menor = mejor)
  config.fb_count = 2;

  // Configurar resolución según PSRAM
  if (psramFound()) {
    config.frame_size = FRAMESIZE_VGA; // 640x480 para mejor rendimiento
    config.jpeg_quality = 10;
    config.fb_count = 2;
  } else {
    config.frame_size = FRAMESIZE_QVGA; // 320x240 sin PSRAM
    config.fb_location = CAMERA_FB_IN_DRAM;
    config.fb_count = 1;
  }

  // Inicializar cámara
  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("❌ Error inicializando cámara: 0x%x\n", err);
    return false;
  }

  // Ajustes del sensor
  sensor_t *s = esp_camera_sensor_get();
  s->set_brightness(s, 0);     // -2 a 2
  s->set_contrast(s, 0);       // -2 a 2
  s->set_saturation(s, 0);     // -2 a 2
  s->set_special_effect(s, 0); // 0 = sin efecto
  s->set_whitebal(s, 1);       // 0 = desactivar, 1 = activar
  s->set_awb_gain(s, 1);       // 0 = desactivar, 1 = activar
  s->set_wb_mode(s, 0);        // 0 a 4 - modo balance de blancos
  s->set_exposure_ctrl(s, 1);  // 0 = desactivar, 1 = activar
  s->set_aec2(s, 0);           // 0 = desactivar, 1 = activar
  s->set_ae_level(s, 0);       // -2 a 2
  s->set_aec_value(s, 300);    // 0 a 1200
  s->set_gain_ctrl(s, 1);      // 0 = desactivar, 1 = activar
  s->set_agc_gain(s, 0);       // 0 a 30
  s->set_gainceiling(s, (gainceiling_t)0); // 0 a 6
  s->set_bpc(s, 0);            // 0 = desactivar, 1 = activar
  s->set_wpc(s, 1);            // 0 = desactivar, 1 = activar
  s->set_raw_gma(s, 1);        // 0 = desactivar, 1 = activar
  s->set_lenc(s, 1);           // 0 = desactivar, 1 = activar
  s->set_hmirror(s, 0);        // 0 = desactivar, 1 = activar
  s->set_vflip(s, 0);          // 0 = desactivar, 1 = activar
  s->set_dcw(s, 1);            // 0 = desactivar, 1 = activar

  Serial.println("✅ Cámara inicializada correctamente");
  return true;
}

// ===========================
// Send Frame to Server
// ===========================
bool sendFrameToServer() {
  camera_fb_t *fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("❌ Error capturando frame");
    errorCount++;
    return false;
  }

  HTTPClient http;
  http.begin(serverURL);
  http.setTimeout(5000); // 5 segundos timeout

  // Crear boundary para multipart/form-data
  String boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW";
  String contentType = "multipart/form-data; boundary=" + boundary;
  http.addHeader("Content-Type", contentType);

  // Construir el body del request
  String bodyStart = "--" + boundary + "\r\n";
  bodyStart += "Content-Disposition: form-data; name=\"image\"; filename=\"frame.jpg\"\r\n";
  bodyStart += "Content-Type: image/jpeg\r\n\r\n";
  
  String bodyEnd = "\r\n--" + boundary + "--\r\n";

  // Calcular tamaño total
  int totalLen = bodyStart.length() + fb->len + bodyEnd.length();
  
  // Crear buffer
  uint8_t *buffer = (uint8_t *)malloc(totalLen);
  if (!buffer) {
    Serial.println("❌ Error asignando memoria");
    esp_camera_fb_return(fb);
    errorCount++;
    return false;
  }

  // Copiar datos al buffer
  memcpy(buffer, bodyStart.c_str(), bodyStart.length());
  memcpy(buffer + bodyStart.length(), fb->buf, fb->len);
  memcpy(buffer + bodyStart.length() + fb->len, bodyEnd.c_str(), bodyEnd.length());

  // Enviar POST request
  int httpResponseCode = http.POST(buffer, totalLen);

  // Limpiar
  free(buffer);
  esp_camera_fb_return(fb);

  if (httpResponseCode > 0) {
    String response = http.getString();
    Serial.printf("✅ Frame enviado [%d] - Código: %d\n", frameCount, httpResponseCode);
    successCount++;
    http.end();
    return true;
  } else {
    Serial.printf("❌ Error enviando frame: %s\n", http.errorToString(httpResponseCode).c_str());
    errorCount++;
    http.end();
    return false;
  }
}

// ===========================
// Setup
// ===========================
void setup() {
  Serial.begin(115200);
  Serial.setDebugOutput(false);
  delay(1000);

  Serial.println("\n\n");
  Serial.println("═══════════════════════════════════════");
  Serial.println("   ESP32-CAM YOLO Client v1.0");
  Serial.println("═══════════════════════════════════════");

  // Configurar WiFi
  Serial.print("📡 Conectando a WiFi");
  WiFi.begin(ssid, password);
  WiFi.setSleep(false);

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 40) {
    delay(500);
    Serial.print(".");
    attempts++;
  }

  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("\n❌ Error conectando a WiFi");
    Serial.println("Reiniciando...");
    ESP.restart();
  }

  Serial.println("\n✅ WiFi conectado");
  Serial.print("📍 IP: ");
  Serial.println(WiFi.localIP());
  Serial.print("📶 Señal: ");
  Serial.print(WiFi.RSSI());
  Serial.println(" dBm");

  // Configurar cámara
  if (!setupCamera()) {
    Serial.println("❌ Error configurando cámara");
    Serial.println("Reiniciando...");
    ESP.restart();
  }

  Serial.println("═══════════════════════════════════════");
  Serial.printf("🎯 Servidor: %s\n", serverURL);
  Serial.printf("⏱️  Intervalo: %lu ms\n", sendInterval);
  Serial.println("═══════════════════════════════════════");
  Serial.println("🚀 Sistema iniciado - Enviando frames...\n");
}

// ===========================
// Loop
// ===========================
void loop() {
  unsigned long currentTime = millis();

  // Verificar conexión WiFi
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("⚠️  WiFi desconectado - Reconectando...");
    WiFi.reconnect();
    delay(5000);
    return;
  }

  // Enviar frame según intervalo
  if (currentTime - lastSendTime >= sendInterval) {
    lastSendTime = currentTime;
    frameCount++;
    
    sendFrameToServer();

    // Mostrar estadísticas cada 10 frames
    if (frameCount % 10 == 0) {
      float successRate = (successCount * 100.0) / frameCount;
      Serial.println("\n───────────────────────────────────────");
      Serial.printf("📊 Estadísticas:\n");
      Serial.printf("   Frames enviados: %lu\n", frameCount);
      Serial.printf("   Exitosos: %lu (%.1f%%)\n", successCount, successRate);
      Serial.printf("   Errores: %lu\n", errorCount);
      Serial.printf("   Memoria libre: %d bytes\n", ESP.getFreeHeap());
      Serial.printf("   WiFi RSSI: %d dBm\n", WiFi.RSSI());
      Serial.println("───────────────────────────────────────\n");
    }
  }

  delay(10); // Pequeña pausa para watchdog
}