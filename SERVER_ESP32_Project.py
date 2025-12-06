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

# ========================================
# CONFIGURACIÓN DE ZONA DE ESTACIONAMIENTO FIJA
# ========================================
PARKING_ZONE = {
    "x1": 260,    # Ajusta estos valores según la imagen
    "y1": 80,
    "x2": 470,
    "y2": 400,
    "color_libre": (0, 255, 0),      # Verde cuando está libre
    "color_ocupado": (0, 0, 255),    # Rojo cuando está ocupado
    "color_mal_estacionado": (0, 165, 255),  # Naranja cuando está mal estacionado
    "thickness": 3
}

# Porcentaje mínimo de solapamiento para considerar "bien estacionado"
OVERLAP_THRESHOLD = 0.70  # 70% del carro debe estar dentro de la zona

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
    "co2_saved": 0,
    "mal_estacionado": False
}

# Constantes para cálculo de CO2
CO2_PER_HOUR_KG = 2.3
CO2_PER_SECOND_G = (CO2_PER_HOUR_KG * 1000) / 3600

def calculate_overlap(box1, box2):
    """
    Calcula el área de solapamiento entre dos cajas
    box1: [x1, y1, x2, y2] - detección del carro
    box2: [x1, y1, x2, y2] - zona de estacionamiento
    Retorna el porcentaje del box1 que está dentro del box2
    """
    x1_inter = max(box1[0], box2[0])
    y1_inter = max(box1[1], box2[1])
    x2_inter = min(box1[2], box2[2])
    y2_inter = min(box1[3], box2[3])
    
    if x2_inter < x1_inter or y2_inter < y1_inter:
        return 0.0
    
    # Área de intersección
    intersection = (x2_inter - x1_inter) * (y2_inter - y1_inter)
    
    # Área del box1 (detección)
    box1_area = (box1[2] - box1[0]) * (box1[3] - box1[1])
    
    if box1_area == 0:
        return 0.0
    
    # Porcentaje de solapamiento
    return intersection / box1_area

def process_frames():
    """Hilo para procesar frames con YOLO"""
    global latest_detection
    
    # Imprimir clases disponibles al inicio
    print("\n🏷️  Clases disponibles en el modelo:")
    for idx, name in model.names.items():
        print(f"   [{idx}] {name}")
    print(f"\n📍 Zona de estacionamiento: ({PARKING_ZONE['x1']}, {PARKING_ZONE['y1']}) -> ({PARKING_ZONE['x2']}, {PARKING_ZONE['y2']})")
    print(f"🎯 Umbral de solapamiento: {OVERLAP_THRESHOLD * 100}%\n")
    
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
            car_detected_in_zone = False
            mal_estacionado = False
            
            parking_box = [PARKING_ZONE['x1'], PARKING_ZONE['y1'], 
                          PARKING_ZONE['x2'], PARKING_ZONE['y2']]
            
            for result in results:
                boxes = result.boxes
                for box in boxes:
                    x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                    conf = float(box.conf[0].cpu().numpy())
                    cls = int(box.cls[0].cpu().numpy())
                    label = model.names[cls]
                    
                    detection_box = [int(x1), int(y1), int(x2), int(y2)]
                    
                    detections.append({
                        "class": label,
                        "confidence": round(conf, 2),
                        "bbox": detection_box
                    })
                    
                    # Verificar si es un vehículo
                    label_lower = label.lower()
                    car_keywords = ['car', 'carro', 'auto', 'automovil', 'vehicle', 
                                  'truck', 'camion', 'van', 'bus', 'suv']
                    
                    is_vehicle = any(keyword in label_lower for keyword in car_keywords)
                    
                    if is_vehicle:
                        car_detected = True
                        
                        # Calcular solapamiento con la zona de estacionamiento
                        overlap = calculate_overlap(detection_box, parking_box)
                        
                        print(f"🔍 Detectado: {label} (confianza: {conf:.2f}, solapamiento: {overlap*100:.1f}%)")
                        
                        if overlap >= OVERLAP_THRESHOLD:
                            # Carro bien estacionado (dentro de la zona)
                            car_detected_in_zone = True
                            print(f"✅ VEHÍCULO BIEN ESTACIONADO: {label}")
                        elif overlap > 0:
                            # Carro parcialmente en la zona (mal estacionado)
                            mal_estacionado = True
                            print(f"⚠️ VEHÍCULO MAL ESTACIONADO: {label} (solo {overlap*100:.1f}% dentro)")
                        else:
                            # Carro completamente fuera de la zona
                            print(f"❌ VEHÍCULO FUERA DE LA ZONA: {label}")
                        
                        # NO DIBUJAR el bounding box individual del carro
                        # Solo mostramos el rectángulo fijo de la zona
            
            # Dibujar SOLO la ZONA DE ESTACIONAMIENTO FIJA
            if car_detected_in_zone:
                # Bien estacionado - zona en rojo
                zone_color = PARKING_ZONE['color_ocupado']
                status_text = "OCUPADO"
            elif mal_estacionado:
                # Mal estacionado - zona en naranja
                zone_color = PARKING_ZONE['color_mal_estacionado']
                status_text = "MAL ESTACIONADO"
            else:
                # Libre - zona en verde
                zone_color = PARKING_ZONE['color_libre']
                status_text = "LIBRE"
            
            cv2.rectangle(annotated_frame, 
                         (PARKING_ZONE['x1'], PARKING_ZONE['y1']),
                         (PARKING_ZONE['x2'], PARKING_ZONE['y2']),
                         zone_color, 
                         PARKING_ZONE['thickness'])
            
            # Agregar etiqueta a la zona
            cv2.putText(annotated_frame, f"ZONA: {status_text}", 
                       (PARKING_ZONE['x1'], PARKING_ZONE['y1'] - 10),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, zone_color, 2)
            
            # Actualizar estado de estacionamiento
            current_time = datetime.now()
            
            if car_detected_in_zone:
                if latest_detection["parking_start_time"] is None:
                    latest_detection["parking_start_time"] = current_time
                    latest_detection["parking_status"] = "OCUPADO"
                    latest_detection["mal_estacionado"] = False
                else:
                    elapsed = (current_time - latest_detection["parking_start_time"]).total_seconds()
                    latest_detection["total_parking_time"] = elapsed
                    latest_detection["co2_saved"] = elapsed * CO2_PER_SECOND_G
            else:
                latest_detection["parking_start_time"] = None
                if mal_estacionado:
                    latest_detection["parking_status"] = "MAL ESTACIONADO"
                    latest_detection["mal_estacionado"] = True
                else:
                    latest_detection["parking_status"] = "LIBRE"
                    latest_detection["mal_estacionado"] = False
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
                "car_detected": car_detected_in_zone
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
                "parking_status": latest_detection["parking_status"],
                "mal_estacionado": latest_detection.get("mal_estacionado", False)
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
        "parking_time": latest_detection["total_parking_time"],
        "mal_estacionado": latest_detection.get("mal_estacionado", False)
    }
    print(f"📤 ESP32 consultó estado: car_detected={response['car_detected']}, status={response['parking_status']}")
    return jsonify(response)

@app.route('/force_detection/<status>', methods=['GET'])
def force_detection(status):
    """Forzar manualmente el estado de detección (para pruebas)"""
    global latest_detection
    if status == "on":
        latest_detection["car_detected"] = True
        latest_detection["parking_status"] = "OCUPADO"
        latest_detection["mal_estacionado"] = False
        if latest_detection["parking_start_time"] is None:
            latest_detection["parking_start_time"] = datetime.now()
        return jsonify({"message": "Detección FORZADA a ON", "car_detected": True})
    else:
        latest_detection["car_detected"] = False
        latest_detection["parking_status"] = "LIBRE"
        latest_detection["mal_estacionado"] = False
        latest_detection["parking_start_time"] = None
        return jsonify({"message": "Detección FORZADA a OFF", "car_detected": False})

@app.route('/set_zone', methods=['POST'])
def set_zone():
    """Endpoint para ajustar la zona de estacionamiento dinámicamente"""
    global PARKING_ZONE
    data = request.json
    
    PARKING_ZONE['x1'] = data.get('x1', PARKING_ZONE['x1'])
    PARKING_ZONE['y1'] = data.get('y1', PARKING_ZONE['y1'])
    PARKING_ZONE['x2'] = data.get('x2', PARKING_ZONE['x2'])
    PARKING_ZONE['y2'] = data.get('y2', PARKING_ZONE['y2'])
    
    return jsonify({
        "message": "Zona actualizada",
        "zone": PARKING_ZONE
    })

if __name__ == '__main__':
    print("=" * 60)
    print("🚀 Servidor de Estacionamiento Inteligente")
    print("=" * 60)
    print(f"📊 Modelo YOLO: {MODEL_PATH}")
    print(f"🌐 Dashboard: http://localhost:5000")
    print(f"🔌 API: http://localhost:5000/detect")
    print(f"🚗 Estado: http://localhost:5000/get_car_status")
    print(f"📍 Zona: ({PARKING_ZONE['x1']}, {PARKING_ZONE['y1']}) -> ({PARKING_ZONE['x2']}, {PARKING_ZONE['y2']})")
    print("=" * 60)
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)