from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import cv2
import numpy as np
from ultralytics import YOLO
import base64
from datetime import datetime, timedelta
import threading
import queue

app = Flask(__name__)
CORS(app)

# Configuración del modelo YOLO
MODEL_PATH = "best.pt"
model = YOLO(MODEL_PATH)

# Cola para procesar frames
frame_queue = queue.Queue(maxsize=10)

# Variables globales mejoradas
latest_detection = {
    "timestamp": None,
    "detections": [],
    "frame_base64": None,
    "processing_time": 0,
    "car_detected": False,
    "parking_status": "LIBRE",
    "parking_start_time": None,
    "total_parking_time": 0,
    "co2_saved": 0
}

# Constantes para cálculo de CO2
CO2_PER_HOUR_KG = 2.3
CO2_PER_SECOND_G = (CO2_PER_HOUR_KG * 1000) / 3600  # gramos por segundo

def process_frames():
    """Hilo para procesar frames con YOLO"""
    global latest_detection
    
    # Imprimir clases disponibles al inicio
    print("\n🏷️  Clases disponibles en el modelo:")
    for idx, name in model.names.items():
        print(f"   [{idx}] {name}")
    print()
    
    while True:
        try:
            frame_data = frame_queue.get(timeout=1)
            start_time = datetime.now()
            
            # Decodificar imagen
            nparr = np.frombuffer(frame_data, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            
            if frame is None:
                continue
            
            # Realizar detección
            results = model(frame, conf=0.25, verbose=False)
            
            # Procesar resultados
            detections = []
            annotated_frame = frame.copy()
            car_detected = False
            
            for result in results:
                boxes = result.boxes
                for box in boxes:
                    x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                    conf = float(box.conf[0].cpu().numpy())
                    cls = int(box.cls[0].cpu().numpy())
                    label = model.names[cls]
                    
                    print(f"🔍 Detectado: {label} (confianza: {conf:.2f})")
                    
                    detections.append({
                        "class": label,
                        "confidence": round(conf, 2),
                        "bbox": [int(x1), int(y1), int(x2), int(y2)]
                    })
                    
                    # Verificar si es un carro
                    label_lower = label.lower()
                    car_keywords = ['car', 'carro', 'auto', 'automovil', 'vehicle', 
                                  'truck', 'camion', 'van', 'bus', 'suv']
                    
                    if any(keyword in label_lower for keyword in car_keywords):
                        car_detected = True
                        print(f"✅ VEHÍCULO DETECTADO: {label}")
                    
                    # Dibujar en el frame
                    color = (0, 255, 0) if car_detected else (255, 0, 0)
                    cv2.rectangle(annotated_frame, (int(x1), int(y1)), 
                                (int(x2), int(y2)), color, 2)
                    cv2.putText(annotated_frame, f"{label} {conf:.2f}", 
                              (int(x1), int(y1-10)), 
                              cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
            
            # Actualizar estado de estacionamiento
            current_time = datetime.now()
            
            if car_detected:
                if latest_detection["parking_start_time"] is None:
                    # Carro recién detectado
                    latest_detection["parking_start_time"] = current_time
                    latest_detection["parking_status"] = "OCUPADO"
                else:
                    # Calcular tiempo de estacionamiento
                    elapsed = (current_time - latest_detection["parking_start_time"]).total_seconds()
                    latest_detection["total_parking_time"] = elapsed
                    latest_detection["co2_saved"] = elapsed * CO2_PER_SECOND_G
            else:
                # No hay carro detectado
                latest_detection["parking_start_time"] = None
                latest_detection["parking_status"] = "LIBRE"
                latest_detection["total_parking_time"] = 0
                latest_detection["co2_saved"] = 0
            
            # Codificar frame anotado
            _, buffer = cv2.imencode('.jpg', annotated_frame)
            frame_base64 = base64.b64encode(buffer).decode('utf-8')
            
            processing_time = (datetime.now() - start_time).total_seconds() * 1000
            
            # Actualizar resultados
            latest_detection.update({
                "timestamp": current_time.isoformat(),
                "detections": detections,
                "frame_base64": frame_base64,
                "processing_time": round(processing_time, 2),
                "car_detected": car_detected
            })
            
        except queue.Empty:
            continue
        except Exception as e:
            print(f"Error procesando frame: {e}")

# Iniciar hilo de procesamiento
processing_thread = threading.Thread(target=process_frames, daemon=True)
processing_thread.start()

@app.route('/')
def index():
    """Página principal"""
    return render_template('index.html')

@app.route('/detect', methods=['POST'])
def detect():
    try:
        if 'image' not in request.files:
            return jsonify({"error": "No image provided"}), 400
        
        file = request.files['image']
        frame_data = file.read()
        
        try:
            frame_queue.put_nowait(frame_data)
            return jsonify({
                "status": "processing",
                "message": "Frame received",
                "car_detected": latest_detection["car_detected"],
                "parking_status": latest_detection["parking_status"]
            })
        except queue.Full:
            return jsonify({
                "status": "busy",
                "message": "Server busy"
            })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/get_detection', methods=['GET'])
def get_detection():
    return jsonify(latest_detection)

@app.route('/get_car_status', methods=['GET'])
def get_car_status():
    """Endpoint para que el ESP32 verifique si hay carro detectado"""
    response = {
        "car_detected": latest_detection["car_detected"],
        "parking_status": latest_detection["parking_status"],
        "parking_time": latest_detection["total_parking_time"]
    }
    print(f"📤 ESP32 consultó estado: car_detected={response['car_detected']}")
    return jsonify(response)

@app.route('/force_detection/<status>', methods=['GET'])
def force_detection(status):
    """Forzar manualmente el estado de detección (para pruebas)"""
    global latest_detection
    if status == "on":
        latest_detection["car_detected"] = True
        latest_detection["parking_status"] = "OCUPADO"
        if latest_detection["parking_start_time"] is None:
            latest_detection["parking_start_time"] = datetime.now()
        return jsonify({"message": "Detección FORZADA a ON", "car_detected": True})
    else:
        latest_detection["car_detected"] = False
        latest_detection["parking_status"] = "LIBRE"
        latest_detection["parking_start_time"] = None
        return jsonify({"message": "Detección FORZADA a OFF", "car_detected": False})

if __name__ == '__main__':
    print("=" * 60)
    print("🚀 Servidor de Estacionamiento Inteligente")
    print("=" * 60)
    print(f"📊 Modelo YOLO: {MODEL_PATH}")
    print(f"🌐 Dashboard: http://localhost:5000")
    print(f"🔌 API: http://localhost:5000/detect")
    print(f"🚗 Estado: http://localhost:5000/get_car_status")
    print("=" * 60)
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)