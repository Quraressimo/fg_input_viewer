# fg_input_viewer
트레이닝식 인풋 뷰어입니다.
GPT 괴롭혀서 만들었습니다.

무슨 기능임?

말 그대로 트레이닝에서 보는 인풋 뷰어를 오버레이식으로 만듬

프레임 | 방향 | 버튼

으로 보여줌


뷰어에서 우클릭하면 설정 버튼이 나옴

입력 표시 방향 :

위 > 아래

아래 > 위

왼쪽 > 오른쪽

오른쪽 > 왼쪽으로 흘러가게함



History entries : 뷰어에 보이는 최대 인풋 갯수임 20~30개가 적당함

History lifetime : 인풋이 남아있는 시간임, 건드린적 없어서 그냥 10해두셈

스틱 데드존 : 힛박써서 모름



Mouse clicks pass through overlay : 마우스 클릭이 안먹게 함, 단축키 ctrl + shift + t누르면 토글 전환

Always on top : 항상 위에

Borderless mode : 있으면 좋으니까



Overlat opacity : 창 투명도, 배경만 투명하게 하고싶었는데 3시간동안 씨름해도 못해서 포기함



Connected controller : 현재 연결중인 패드, 키보드는 안먹는데 내일 호환 시켜봄





Game / profile : 프로필별로 뷰어 커스텀 가능



Save / Delete : 프로필 저장, 삭제

Button mappings : 키 커스텀 관리

Add row : 버튼 추가



누르면 이렇게 줄 생김



Delete selected : 줄 삭제





Detect button index : Listen for next press 버튼을 누르고 컨트롤러 버튼을 누르면 해당 버튼의 인덱스가 뜸



버튼 설정법

일단 Listen for next press 버튼을 누르고 버튼을 누름



그럼 Input칸에 인덱스인 2가 들어간 버튼 줄이 생김



버?그로는 선택 중인 열에 input 인덱스를 넣는 것이기 때문에 아무것도 없을 때 하면 중복으로 들어감

낼 아침에 디폴트 버튼 셋 좀 만듬





그리고 옆에 name 입력하고 버튼색 바꾸고 텍스트 색 바꾸고 하면 짜잔

프로필 이름 설정하고 SAVE 누르면 된다







이렇게 프로필을 만들어 놓으면 빠른 스왑이 가능





컨트롤러의 모든 버튼을 인식하기 때문에 스타트, 셀렉도 확인 가능





오버레이와 버튼 프로필은 json파일로 자동으로 동일 디렉토리에 생성함

뭐 업뎃해서 py파일 다시 다운받아도 호환가능

