# 모바일 OCR 문서 스캔 앱 - 개발 가이드라인

**문서 작성일**: 2026-06-09  
**대상**: 개발팀 (백엔드 팀, 모바일 팀)  
**상태**: 개발 시작 준비 완료

---

## 프로젝트 개요

### 목표
휴대폰 카메라로 보험 청구 서류를 촬영하고, 즉시 OCR 처리하여 구조화된 데이터로 변환하는 모바일 앱 개발

### 핵심 기능
1. **카메라 촬영**: Android 기기에서 보험 서류 사진 촬영
2. **OCR 처리**: Azure Document Intelligence를 통한 문서 인식
3. **표 구조 추출**: 표의 행·열·셀 정보 추출
4. **결과 확인**: 3개 탭으로 원본/텍스트/시각화 표시
5. **표 수정**: 필요 시 사용자가 수동으로 표 수정

### 대상 문서
- 진료비 세부내역서 (최우선 - 표가 복잡함)
- 진단서 (텍스트 위주)
- 영수증 (간단한 표)

---

## 최종 기술 스택 결정

### 모바일 앱
```
프레임워크: Flutter (Android 전용 배포)
언어: Dart
최소 SDK: API Level 24 (Android 7.0)
최대 SDK: API Level 34 (Android 14)

필수 라이브러리:
- camera: 카메라 접근 및 실시간 미리보기
- image_picker: 갤러리에서 이미지 선택
- image: 이미지 압축
- http (또는 dio): HTTP 통신
- custom_paint: 표 시각화
- provider: 상태 관리
- intl: 날짜/시간 포맷팅
```

### 백엔드
```
기술: 기존 RAG 서버 유지
새 엔드포인트: POST /api/documents/ocr

Node.js인 경우:
- @azure/ai-form-recognizer (Azure SDK)
- express (라우팅)
- multer (파일 업로드 - 선택)

Python인 경우:
- azure-ai-documentintelligence (Azure SDK)
- fastapi 또는 flask
- python-dotenv
```

### OCR API
```
선택: Azure Document Intelligence
- 초기 500건 무료
- 표 추출 정확도 최고 (95%+)
- 셀 위치 정보(bbox) 완벽 제공

필요 정보:
- Azure 구독 ID
- Document Intelligence API Endpoint
- API Key (환경변수로 관리)
```

---

## 개발 환경 준비 체크리스트

### 모든 팀원
```
[ ] Git 저장소 클론
[ ] 개발 브랜치 생성: feature/mobile-ocr-<이름>
[ ] Slack/Discord 채널 참여
[ ] 프로젝트 일정 공유
```

### 백엔드 팀
```
[ ] Node.js 16+ 또는 Python 3.8+ 설치
[ ] 기존 RAG 서버 로컬 실행 확인
[ ] Azure 계정 생성 (구독 필요)
[ ] Document Intelligence 리소스 생성
[ ] API Key 및 Endpoint URL 확보
[ ] 로컬 환경변수 설정 (.env 파일)
[ ] Postman 또는 curl로 API 테스트 준비
```

### 모바일 팀
```
[ ] Flutter SDK 3.0+ 설치
[ ] Android Studio 설치
[ ] Android Emulator 또는 테스트 기기 준비
[ ] VS Code + Flutter/Dart 플러그인 설치
[ ] pubspec.yaml 의존성 다운로드
[ ] 프로젝트 실행 확인 (flutter run)
```

---

## 개발 순서 (병렬 진행)

### Week 1-2: 백엔드 구현 (최우선)

**Task 1: Azure 셋업 (1-2일)**
```
목표: Azure API가 정상 작동하는지 확인

구현:
1. Azure Portal에서 Document Intelligence 리소스 생성
2. API Key 및 Endpoint URL 확보
3. Postman으로 직접 테스트:
   POST https://<endpoint>.cognitiveservices.azure.com/formrecognizer/documentModels/prebuilt-read:analyze?api-version=2023-07-31
   
   Header:
   - Ocp-Apim-Subscription-Key: <API_KEY>
   - Content-Type: application/octet-stream
   
   Body: 실제 보험 서류 이미지

4. 응답 확인:
   {
     "status": "succeeded",
     "analyzeResult": {
       "pages": [...],
       "tables": [...]
     }
   }

검증: Azure가 한글 텍스트를 정확히 인식하는지 확인
```

**Task 2: API 엔드포인트 구현 (2-3일)**
```
목표: POST /api/documents/ocr 엔드포인트 완성

구현 (Node.js 예시):
app.post('/api/documents/ocr', async (req, res) => {
  try {
    // 1. Base64 이미지 받기
    const { image, documentType, metadata } = req.body;
    
    // 2. 이미지 검증
    if (!image || image.length > 3 * 1024 * 1024) {
      return res.status(400).json({ 
        error: 'IMAGE_TOO_LARGE' 
      });
    }
    
    // 3. Azure 호출
    const client = new DocumentAnalysisClient(
      endpoint, 
      new AzureKeyCredential(key)
    );
    
    const imageBuffer = Buffer.from(image, 'base64');
    
    const poller = await client.beginAnalyzeDocument(
      "prebuilt-read",
      imageBuffer,
      { contentType: "image/jpeg" }
    );
    
    const result = await poller.pollUntilDone();
    
    // 4. 응답 반환
    return res.json({
      success: true,
      result: normalizeAzureResponse(result)
    });
    
  } catch (error) {
    return res.status(500).json({
      success: false,
      error: error.message
    });
  }
});

테스트:
curl -X POST http://localhost:3000/api/documents/ocr \
  -H "Content-Type: application/json" \
  -d '{
    "image": "<base64_string>",
    "documentType": "detailed-breakdown"
  }'
```

**Task 3: 데이터 정규화 (2-3일)**
```
목표: Azure 응답을 모바일이 사용할 수 있는 형식으로 변환

구현:
function normalizeAzureResponse(azureResult) {
  const tables = azureResult.tables.map((table, idx) => ({
    table_id: idx,
    rows: table.rowCount,
    cols: table.columnCount,
    headers: extractHeaders(table),
    cells: table.cells.map(cell => ({
      row: cell.rowIndex,
      col: cell.columnIndex,
      text: cell.content,
      bbox: calculateBbox(cell.boundingRegions[0]),
      confidence: cell.confidence || 1.0
    }))
  }));
  
  return {
    raw_text: extractAllText(azureResult),
    tables: tables,
    metadata: {
      processingTime: Date.now() - startTime,
      provider: 'azure',
      confidence: calculateOverallConfidence(tables)
    }
  };
}

핵심: boundingRegion (polygon 형태)을 bbox (x, y, width, height)로 변환
- x, y: 폴리곤의 최소값
- width, height: 폴리곤의 최대값 - 최소값
```

**Task 4: 에러 처리 (1-2일)**
```
처리할 에러:
- INVALID_IMAGE_FORMAT: JPEG 아닌 파일
- IMAGE_TOO_LARGE: 3MB 초과
- AZURE_API_ERROR: Azure 서버 오류
- TIMEOUT: 30초 이상 응답 없음

각 에러에 대한 HTTP 상태 코드:
- 400: 클라이언트 오류
- 413: 파일 크기 초과
- 503: 서버 오류
- 504: 타임아웃
```

**Task 5: 테스트 (2-3일)**
```
테스트할 시나리오:
1. 진료비 세부내역서 (5개)
2. 진단서 (3개)
3. 영수증 (2개)

검증 기준:
- 텍스트 인식: 95% 이상 정확
- 표 인식: 모든 표 감지
- 셀 위치: bbox 정확도 90% 이상
- 응답 시간: 평균 5-10초

성능 측정:
- 처리 시간 기록
- 에러율 추적
- 정확도 통계
```

---

### Week 2-3: 모바일 기본 기능

**Task 1: 프로젝트 초기화 (1일)**
```
flutter create mobile_ocr_scanner
cd mobile_ocr_scanner

pubspec.yaml 업데이트:
dependencies:
  camera: ^0.10.0+4
  image_picker: ^0.8.7+1
  image: ^4.0.0
  http: ^1.1.0
  provider: ^6.0.0
  intl: ^0.18.0

flutter pub get
```

**Task 2: 카메라 화면 (3-4일)**
```
구현할 화면:
lib/screens/camera_screen.dart

기능:
1. 카메라 권한 요청
2. 실시간 카메라 프리뷰
3. 프레임 가이드 (흰색 점선 사각형)
4. 촬영 버튼 (원형, 파란색)
5. 갤러리 버튼

코드 구조:
class CameraScreen extends StatefulWidget {
  @override
  _CameraScreenState createState() => _CameraScreenState();
}

class _CameraScreenState extends State<CameraScreen> {
  CameraController? _controller;
  
  @override
  void initState() {
    super.initState();
    _initializeCamera();
  }
  
  Future<void> _initializeCamera() async {
    // 권한 요청
    // 카메라 컨트롤러 초기화
    // 미리보기 시작
  }
  
  Future<void> _takePicture() async {
    // 사진 촬영
    // 처리 화면으로 이동
  }
  
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: CameraPreview(_controller),
      floatingActionButton: FloatingActionButton(
        onPressed: _takePicture,
        child: Icon(Icons.camera_alt),
      ),
    );
  }
}

테스트:
- 카메라 켜기 (권한 요청 확인)
- 촬영 버튼 누르기 (사진 저장 확인)
- 갤러리에서 선택 (이미지 로드 확인)
```

**Task 3: 이미지 처리 (2-3일)**
```
구현:
lib/services/image_service.dart

기능:
1. 이미지 크기 확인
2. 필요시 압축 (2-3MB 목표)
3. Base64 인코딩

코드:
class ImageService {
  static Future<String> compressAndEncode(File imageFile) async {
    // 1. 파일 크기 확인
    int fileSizeInBytes = await imageFile.length();
    
    // 2. 압축 필요 시 진행
    if (fileSizeInBytes > 3 * 1024 * 1024) {
      final image = img.decodeImage(imageFile.readAsBytesSync());
      
      // 너비를 800px으로 조정
      final resized = img.copyResize(image,
        width: 800,
        height: (image.height * 800 ~/ image.width)
      );
      
      // JPEG 품질 80%로 저장
      final compressed = img.encodeJpg(resized, quality: 80);
      
      // Base64 인코딩
      return base64Encode(compressed);
    } else {
      return base64Encode(imageFile.readAsBytesSync());
    }
  }
}

테스트:
- 큰 이미지 (10MB) 압축
- 작은 이미지 (1MB) 유지
- Base64 인코딩 확인
```

**Task 4: 백엔드 통신 (2-3일)**
```
구현:
lib/services/ocr_service.dart

기능:
1. HTTP POST 요청
2. 타임아웃 처리 (30초)
3. 에러 처리

코드:
class OcrService {
  static const String API_URL = 'http://your-backend:3000/api/documents/ocr';
  
  static Future<OcrResult> processDocument({
    required String imageBase64,
    required String documentType,
  }) async {
    try {
      final response = await http.post(
        Uri.parse(API_URL),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({
          'image': imageBase64,
          'documentType': documentType,
          'metadata': {
            'timestamp': DateTime.now().toIso8601String(),
            'deviceType': 'android',
            'appVersion': '1.0.0'
          }
        }),
      ).timeout(Duration(seconds: 30), onTimeout: () {
        throw TimeoutException('OCR processing timeout');
      });
      
      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        return OcrResult.fromJson(data['result']);
      } else {
        throw Exception('API Error: ${response.body}');
      }
    } catch (e) {
      rethrow;
    }
  }
}

테스트:
- 정상 응답 처리
- 타임아웃 처리
- 에러 응답 처리
```

---

### Week 3-4: 결과 화면 (3개 탭)

**Task 5: 원본 탭 (1-2일)**
```
구현:
lib/screens/results_screen.dart -> OriginalTab

기능:
- 촬영한 이미지 표시
- 핀치 확대/축소
- 더블탭 토글
```

**Task 6: 텍스트 탭 (1일)**
```
구현:
lib/screens/results_screen.dart -> TextTab

기능:
- raw_text 표시
- 스크롤 가능
- 글자 크기 14-16px
```

**Task 7: 시각화 탭 (3-4일) - 복잡함**
```
구현:
lib/screens/results_screen.dart -> VisualizationTab
lib/widgets/table_painter.dart

기능:
- CustomPaint로 표 셀 그리기
- 각 셀을 bbox 정보로 렌더링
- 헤더/데이터 행 다른 색상

핵심 코드:
class TablePainter extends CustomPainter {
  final List<Cell> cells;
  final Size imageSize;
  
  @override
  void paint(Canvas canvas, Size size) {
    for (var cell in cells) {
      // bbox를 화면 좌표로 변환
      final paint = Paint()
        ..color = cell.isHeader 
          ? Colors.blue.withOpacity(0.7)
          : Colors.green.withOpacity(0.7)
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2;
      
      final rect = Rect.fromLTWH(
        cell.bbox.x,
        cell.bbox.y,
        cell.bbox.width,
        cell.bbox.height
      );
      
      canvas.drawRect(rect, paint);
      
      // 셀 텍스트 그리기
      final textPainter = TextPainter(
        text: TextSpan(
          text: cell.text,
          style: TextStyle(color: Colors.white, fontSize: 8)
        ),
        textDirection: TextDirection.ltr,
      );
      textPainter.layout();
      textPainter.paint(canvas, Offset(rect.left, rect.top));
    }
  }
  
  @override
  bool shouldRepaint(TablePainter oldDelegate) => true;
}

테스트:
- 단일 표 렌더링
- 다중 표 렌더링
- 확대/축소 시 정확성
```

---

### Week 4-5: 표 수정 화면

**Task 8: 표 수정 화면 (4-5일) - 가장 복잡**
```
구현:
lib/screens/table_editor_screen.dart

기능:
1. 포맷된 테이블 렌더링
2. 셀 클릭 → 텍스트 입력
3. 행 추가/삭제
4. 저장/취소

상태 관리:
Provider를 사용해서 수정된 표 데이터 추적

class TableEditorProvider extends ChangeNotifier {
  late List<TableData> tables;
  int currentTableIndex = 0;
  
  void updateCell(int tableId, int row, int col, String text) {
    tables[tableId].cells
      .where((c) => c.row == row && c.col == col)
      .first
      .text = text;
    notifyListeners();
  }
  
  void addRow(int tableId) {
    // 마지막 행 복사 후 추가
  }
  
  void deleteRow(int tableId, int row) {
    tables[tableId].cells.removeWhere((c) => c.row == row);
  }
}

UI 구현:
- DataTable 또는 커스텀 테이블 위젯
- 셀 탭 시 TextField로 전환
- 수정된 셀 하이라이팅 (노란색)

테스트:
- 셀 수정 저장 확인
- 행 추가/삭제 확인
- 여러 표 전환 확인
```

**Task 9: 데이터 직렬화 (1-2일)**
```
구현:
lib/models/ocr_result.dart

기능:
수정된 표 데이터를 JSON으로 변환해서 백엔드로 전송

코드:
class OcrResult {
  List<TableData> tables;
  String rawText;
  
  Map<String, dynamic> toJson() => {
    'tables': tables.map((t) => t.toJson()).toList(),
    'raw_text': rawText,
  };
}

class TableData {
  int tableId;
  int rows;
  int cols;
  List<Cell> cells;
  
  Map<String, dynamic> toJson() => {
    'table_id': tableId,
    'rows': rows,
    'cols': cols,
    'cells': cells.map((c) => c.toJson()).toList(),
  };
}

백엔드로 전송:
final json = editedResult.toJson();
await http.post(
  Uri.parse('$API_URL/save'),
  body: jsonEncode(json),
);
```

---

### Week 5-6: 통합 및 최적화

**Task 10: 처리 중 화면**
```
구현:
lib/screens/loading_screen.dart

기능:
- 로딩 애니메이션
- 프로그래스바
- 타임아웃 메시지
- 취소 버튼
```

**Task 11: 전체 흐름 테스트**
```
시나리오:
1. 카메라 → 사진 촬영 → 처리 → 결과 표시
2. 결과 확인 → 표 수정 필요 → 수정 화면
3. 수정 → 저장 → 데이터 전송 확인
4. 재촬영 또는 종료

실제 기기에서 테스트:
- Samsung Galaxy (권장)
- Google Pixel
- 최소 API 24 이상
```

**Task 12: 성능 최적화**
```
확인 사항:
- 메모리 사용: < 200MB
- 이미지 로드 시간: < 2초
- 표 렌더링: < 1초
- 배터리 소비: 1시간 사용 시 < 10%

프로파일링 도구:
- Android Studio Profiler
- Dart DevTools
```

---

## API 스펙 요약

### Request
```json
POST /api/documents/ocr

{
  "image": "base64_encoded_jpeg_string",
  "documentType": "receipt|diagnosis|detailed-breakdown",
  "metadata": {
    "timestamp": "2026-06-09T15:30:00Z",
    "deviceType": "android",
    "appVersion": "1.0.0"
  }
}
```

### Response (Success)
```json
{
  "success": true,
  "result": {
    "raw_text": "인식된 모든 텍스트...",
    "tables": [
      {
        "table_id": 0,
        "rows": 15,
        "cols": 5,
        "headers": ["항목", "수량", "단가", "급여", "비급여"],
        "cells": [
          {
            "row": 1,
            "col": 0,
            "text": "초진료",
            "bbox": {"x": 50, "y": 100, "width": 150, "height": 30},
            "confidence": 0.98
          }
        ]
      }
    ],
    "metadata": {
      "processingTime": 5200,
      "provider": "azure",
      "confidence": 0.95
    }
  }
}
```

### Response (Error)
```json
{
  "success": false,
  "error": {
    "code": "INVALID_IMAGE_FORMAT",
    "message": "Invalid image format. Only JPEG is supported."
  }
}
```

---

## 테스트 전략

### Unit Tests (백엔드)
```
테스트할 함수:
- Base64 디코딩
- 이미지 검증
- Azure 응답 파싱
- bbox 계산
- 에러 처리

테스트 도구:
- Node.js: Jest
- Python: pytest
```

### Integration Tests
```
테스트 시나리오:
1. 엔드-투-엔드 (E2E)
   앱에서 사진 촬영 → API 호출 → 결과 표시

2. 다양한 문서 타입
   - 진료비 세부내역서 (5개)
   - 진단서 (3개)
   - 영수증 (2개)

3. 엣지 케이스
   - 어두운 사진
   - 기울어진 문서
   - 작은 글씨
   - 손상된 문서

검증:
- 텍스트 인식 정확도 95% 이상
- 표 구조 정확도 90% 이상
- 응답 시간 5-10초
```

### 성능 테스트
```
측정 항목:
- 평균 응답 시간
- 에러율
- 메모리 사용량
- 네트워크 대역폭

목표:
- 평균 응답: 7초 이하
- 에러율: < 2%
- 메모리: < 200MB
- 네트워크: < 3MB (압축 후)
```

---

## 배포 가이드

### 개발 단계
```
1. 로컬 개발 환경에서 테스트
2. 테스트 기기 (Android Emulator 또는 실제 기기)
3. 팀 내부 테스트
```

### 테스트 배포
```
Google Play Console:
1. 내부 테스트 트랙 생성
2. APK 업로드
3. 팀원 초대
4. 테스트 피드백 수집
```

### 배포 전 체크리스트
```
[ ] 모든 테스트 통과
[ ] 프라이버시 정책 작성
[ ] 앱 아이콘, 스크린샷 준비
[ ] 앱 설명 작성
[ ] 권한 검토 (카메라, 저장소)
[ ] 버전 번호 설정 (1.0.0)
[ ] ProGuard 설정 (난독화)
[ ] 서명 키 생성
```

---

## 주의사항

### 보안
```
❌ 금지:
- API Key를 코드에 하드코딩
- 민감한 정보 로그에 남기기
- HTTP 사용 (HTTPS만 사용)

✅ 필수:
- 환경변수로 API Key 관리
- 데이터 암호화 (전송, 저장)
- 타임아웃 설정 (30초)
```

### 개인정보 보호
```
진료비 서류에는 민감한 정보 포함:
- 환자명
- 주민번호
- 진단명
- 병원명

주의 사항:
- 이미지는 처리 후 즉시 삭제
- 로그에 텍스트 내용 기록 금지
- HTTPS 암호화 전송 필수
- 사용자에게 개인정보 보호 안내
```

### 성능
```
⚠️ 주의할 부분:
- 이미지 압축 (3MB 초과 금지)
- 메모리 누수 (이미지 캐싱)
- 네트워크 타임아웃 (30초)
- UI 프레임 드롭 (표 렌더링)

최적화 팁:
- 이미지는 메모리에서 즉시 해제
- 표 렌더링은 비동기로
- 캐싱 사용 (타입, 설정 등)
```

---

## 커뮤니케이션 가이드

### 진행 보고
```
매주 금요일 16:00 (또는 합의한 시간):
- 백엔드: 완료한 태스크, 블로킹 이슈
- 모바일: 완료한 태스크, 질문사항
- 전체: 다음주 계획 확인
```

### Issue Tracking
```
GitHub Issues 또는 Linear:
- 제목: [Backend/Mobile] 간단한 설명
- 레이블: bug/feature/improvement
- 담당자: 팀원 배정
- 진행도: To Do / In Progress / Done
```

### Code Review
```
Pull Request:
- 작은 단위 (500줄 이하)
- 설명: 변경 사항과 이유
- 테스트: 유닛 테스트 포함
- 승인: 2인 이상 검토
```

---

## 트러블슈팅

### 백엔드 문제

**Azure API 타임아웃**
```
증상: 30초 이상 응답 없음
해결:
1. Azure 지역 확인 (한국 권장)
2. 이미지 크기 확인 (3MB 이하)
3. 네트워크 연결 확인
4. Azure 서비스 상태 확인
```

**표 인식 안 됨**
```
증상: tables[] 배열이 비어있음
해결:
1. 이미지 품질 확인
2. 다른 이미지로 테스트
3. Azure 신뢰도 로그 확인
4. 문서 타입 재분류
```

### 모바일 문제

**카메라 켜지지 않음**
```
증상: 카메라 화면 검은색
해결:
1. 권한 확인 (Settings → Apps → 카메라)
2. 다른 앱에서 카메라 사용 중인지 확인
3. 기기 재부팅
4. 다른 테스트 기기에서 시도
```

**이미지 압축 오류**
```
증상: 압축 후 이미지 손상
해결:
1. 이미지 라이브러리 업데이트
2. 압축 품질 조정 (80% → 90%)
3. 단계적 압축 (너비 조정 후 품질 조정)
```

**메모리 부족**
```
증상: 앱 크래시 (OutOfMemory)
해결:
1. 이미지 해제 시점 확인
2. 캐시 크기 제한
3. 대용량 이미지 처리 전에 해제
4. Profiler로 메모리 누수 확인
```

---

## 다음 단계

### 개발 시작 전
```
[ ] 이 가이드 라인 팀 리뷰
[ ] Azure 계정 및 API 키 발급
[ ] Flutter SDK 설치 및 테스트
[ ] 개발 환경 구성
[ ] Git 브랜치 생성
```

### 개발 중
```
[ ] 주간 진행 보고
[ ] Code Review 진행
[ ] 테스트 케이스 작성
[ ] 문서 업데이트
```

### 개발 완료 후
```
[ ] 통합 테스트
[ ] 성능 최적화
[ ] 배포 준비
[ ] 앱 스토어 등록
```

---

## 참고 자료

- [Flutter 공식 문서](https://flutter.dev/docs)
- [Azure Document Intelligence](https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/)
- [HTTP 상태 코드](https://developer.mozilla.org/en-US/docs/Web/HTTP/Status)
- [프로토콜 버퍼](https://developers.google.com/protocol-buffers)

---

**문서 작성일**: 2026-06-09  
**최종 검토**: eundeo  
**승인 필요**: 프로젝트 리드

