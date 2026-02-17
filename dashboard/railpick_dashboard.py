"""
RailPick Firestore 대시보드
실행: streamlit run dashboard/railpick_dashboard.py
"""
import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime, timezone, timedelta
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd

# 페이지 설정
st.set_page_config(
    page_title="RailPick Dashboard",
    page_icon="🚄",
    layout="wide"
)

# Firebase 초기화
@st.cache_resource
def init_firebase():
    if not firebase_admin._apps:
        import json
        try:
            # Streamlit Cloud: Secrets에서 서비스 계정 키를 개별 필드로 로드
            key_dict = dict(st.secrets["firebase_service_account"])
            cred = credentials.Certificate(key_dict)
        except Exception as e:
            # 로컬 폴백 - 여러 파일명 시도
            import glob
            key_files = glob.glob('railpick-firebase-adminsdk-*.json') + glob.glob('../railpick-firebase-adminsdk-*.json')
            if not key_files:
                st.error(f"Firebase 키를 찾을 수 없습니다. Secrets 설정을 확인하세요.\n에러: {e}")
                st.stop()
            cred = credentials.Certificate(key_files[0])
        firebase_admin.initialize_app(cred)
    return firestore.client(database_id='railpick')

db = init_firebase()

# 데이터 로드 (5분 캐시)
@st.cache_data(ttl=300)
def load_all_data():
    now = datetime.now(timezone.utc)
    data = {}

    # users
    ADMIN_EMAILS = {'j2348sh@gmail.com', 'j2348sh@naver.com', 'j23488sh@gmail.com', 'j234888sh@gmail.com', 'j234ish@gmail.com'}
    all_users = list(db.collection('users').stream())
    # ⭐ 관리자 제외 (이후 모든 루프에서 자동 제외)
    users = [u for u in all_users if u.to_dict().get('email', '') not in ADMIN_EMAILS]
    user_list = []
    devices_total = 0
    tickets_total = 0
    for u in users:
        d = u.to_dict()
        subcols = list(u.reference.collections())
        dev_count = 0
        tkt_count = 0
        for sc in subcols:
            docs = list(sc.stream())
            if sc.id == 'devices': dev_count = len(docs)
            elif sc.id == 'tickets': tkt_count = len(docs)
        devices_total += dev_count
        tickets_total += tkt_count
        user_list.append({
            'id': u.id,
            'name': d.get('displayName', ''),
            'email': d.get('email', ''),
            'provider': d.get('lastLoginProvider', 'unknown'),
            'last_login': d.get('lastLogin'),
            'devices': dev_count,
            'tickets': tkt_count
        })
    data['users'] = user_list
    data['devices_total'] = devices_total
    data['tickets_total'] = tickets_total

    # device_trials
    trials = list(db.collection('device_trials').stream())
    recent_1d = recent_7d = recent_30d = 0
    daily_counts = {}
    for t in trials:
        td = t.to_dict()
        last_seen = td.get('last_seen')
        if last_seen and hasattr(last_seen, 'timestamp'):
            ts = datetime.fromtimestamp(last_seen.timestamp(), tz=timezone.utc)
            diff = now - ts
            if diff.days <= 1: recent_1d += 1
            if diff.days <= 7: recent_7d += 1
            if diff.days <= 30: recent_30d += 1
            day_key = ts.strftime('%Y-%m-%d')
            daily_counts[day_key] = daily_counts.get(day_key, 0) + 1
    data['trials_total'] = len(trials)
    data['recent_1d'] = recent_1d
    data['recent_7d'] = recent_7d
    data['recent_30d'] = recent_30d
    data['daily_active'] = daily_counts

    # consent_logs
    consents = list(db.collection('consent_logs').stream())
    consent_true = sum(1 for c in consents if c.to_dict().get('auto_reserve_consent') == True)
    data['consent_total'] = len(consents)
    data['consent_agreed'] = consent_true

    # email_mappings
    data['email_count'] = len(list(db.collection('email_mappings').stream()))

    # devices 모델 분석
    device_models = {}
    provider_devices = {}
    for u in users:
        ud = next((x for x in user_list if x['id'] == u.id), None)
        provider = ud['provider'] if ud else 'unknown'
        devs = list(db.collection('users').document(u.id).collection('devices').stream())
        dev_count = len(devs)
        provider_devices.setdefault(provider, []).append(dev_count)
        for d in devs:
            dd = d.to_dict()
            model = dd.get('deviceModel', 'unknown')
            device_models[model] = device_models.get(model, 0) + 1
    data['device_models'] = device_models
    data['provider_devices'] = provider_devices

    # tickets 구간 분석
    routes = {}
    train_types = {}
    seat_classes = {}
    for u in users:
        tkts = list(db.collection('users').document(u.id).collection('tickets').stream())
        for t in tkts:
            td = t.to_dict()
            dep = td.get('departureStation', '')
            arr = td.get('arrivalStation', '')
            tt = td.get('trainType', '')
            sc = td.get('seatClass', '')
            st_type = td.get('serviceType', '')
            if dep and arr:
                route = f"{dep} → {arr}"
                routes[route] = routes.get(route, 0) + 1
            if tt:
                train_types[tt] = train_types.get(tt, 0) + 1
            if sc:
                seat_classes[sc] = seat_classes.get(sc, 0) + 1
    data['routes'] = routes
    data['train_types'] = train_types
    data['seat_classes'] = seat_classes

    # 신규 기기 추이 (created_at 기반)
    new_device_daily = {}
    for t in trials:
        td = t.to_dict()
        created = td.get('created_at') or td.get('first_install_time')
        if created and hasattr(created, 'timestamp'):
            ts = datetime.fromtimestamp(created.timestamp(), tz=timezone.utc)
            day_key = ts.strftime('%Y-%m-%d')
            new_device_daily[day_key] = new_device_daily.get(day_key, 0) + 1
    data['new_device_daily'] = new_device_daily

    return data

# 데이터 로드
data = load_all_data()

# 헤더
st.title("🚄 RailPick 대시보드")
st.caption(f"마지막 갱신: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} (5분 캐시)")

# 새로고침 버튼
if st.button("🔄 새로고침"):
    st.cache_data.clear()
    st.rerun()

st.divider()

# ========== 핵심 지표 (KPI) ==========
col1, col2, col3, col4, col5 = st.columns(5)
with col1:
    st.metric("📱 총 기기", f"{data['trials_total']:,}")
with col2:
    st.metric("🟢 오늘 활성", f"{data['recent_1d']:,}")
with col3:
    st.metric("📊 7일 활성", f"{data['recent_7d']:,}")
with col4:
    st.metric("👤 로그인 사용자", f"{len(data['users'])}")
with col5:
    rate = data['consent_agreed'] / max(data['consent_total'], 1) * 100
    st.metric("✅ 동의율", f"{rate:.0f}%")

st.divider()

# ========== 차트 영역 ==========
chart_col1, chart_col2 = st.columns(2)

# 로그인 제공자 파이 차트
with chart_col1:
    st.subheader("🔐 로그인 제공자 분포")
    providers = {}
    for u in data['users']:
        p = u['provider']
        if p == 'unknown':
            continue
        providers[p] = providers.get(p, 0) + 1
    if providers:
        fig = px.pie(
            names=list(providers.keys()),
            values=list(providers.values()),
            color_discrete_map={'kakao': '#FEE500', 'google': '#4285F4', 'naver': '#03C75A'},
            hole=0.4
        )
        fig.update_layout(height=300, margin=dict(t=20, b=20, l=20, r=20))
        st.plotly_chart(fig, use_container_width=True)

# 동의율 게이지
with chart_col2:
    st.subheader("📋 스마트 예약 동의 현황")
    fig = go.Figure(go.Indicator(
        mode="gauge+number+delta",
        value=data['consent_agreed'],
        delta={'reference': data['consent_total'], 'relative': False, 'valueformat': '.0f'},
        title={'text': f"동의 / 전체 ({data['consent_total']}건)"},
        gauge={
            'axis': {'range': [0, data['consent_total']]},
            'bar': {'color': '#03C75A'},
            'steps': [
                {'range': [0, data['consent_total']], 'color': '#f0f0f0'}
            ]
        }
    ))
    fig.update_layout(height=300, margin=dict(t=40, b=20, l=20, r=20))
    st.plotly_chart(fig, use_container_width=True)

st.divider()

# 일별 활성 기기 차트
st.subheader("📈 일별 활성 기기 (최근 30일)")
daily = data['daily_active']
if daily:
    # 최근 30일만 필터
    cutoff = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
    filtered = {k: v for k, v in sorted(daily.items()) if k >= cutoff}
    if filtered:
        df = pd.DataFrame(list(filtered.items()), columns=['날짜', '활성 기기'])
        fig = px.bar(df, x='날짜', y='활성 기기', color_discrete_sequence=['#0052A4'])
        fig.update_layout(height=300, margin=dict(t=20, b=20))
        st.plotly_chart(fig, use_container_width=True)

st.divider()

# ========== 기기 모델 + 인기 구간 ==========
model_col, route_col = st.columns(2)

# 기기 모델 분포
with model_col:
    st.subheader("📱 기기 모델 분포")
    models = data.get('device_models', {})
    if models:
        # 모델명 정리 (samsung SM-S928N → Galaxy S25 Ultra 등)
        model_names = {
            # Galaxy S 시리즈
            'SM-S938N': 'Galaxy S25 Ultra', 'SM-S937N': 'Galaxy S25 Edge', 'SM-S936N': 'Galaxy S25+', 'SM-S931N': 'Galaxy S25',
            'SM-S928N': 'Galaxy S24 Ultra', 'SM-S926N': 'Galaxy S24+', 'SM-S921N': 'Galaxy S24', 'SM-S721N': 'Galaxy S24 FE',
            'SM-S918N': 'Galaxy S23 Ultra', 'SM-S916N': 'Galaxy S23+', 'SM-S911N': 'Galaxy S23', 'SM-S711N': 'Galaxy S23 FE',
            'SM-S908N': 'Galaxy S22 Ultra', 'SM-S906N': 'Galaxy S22+', 'SM-S901N': 'Galaxy S22',
            'SM-G998N': 'Galaxy S21 Ultra', 'SM-G996N': 'Galaxy S21+', 'SM-G991N': 'Galaxy S21',
            'SM-G988N': 'Galaxy S20 Ultra', 'SM-G986N': 'Galaxy S20+', 'SM-G981N': 'Galaxy S20', 'SM-G781N': 'Galaxy S20 FE',
            # Galaxy Note
            'SM-N986N': 'Galaxy Note20 Ultra', 'SM-N981N': 'Galaxy Note20',
            # Galaxy Z Fold
            'SM-F966N': 'Galaxy Z Fold7', 'SM-F958N': 'Galaxy Z Fold SE',
            'SM-F956N': 'Galaxy Z Fold6', 'SM-F946N': 'Galaxy Z Fold5', 'SM-F936N': 'Galaxy Z Fold4',
            'SM-F926N': 'Galaxy Z Fold3', 'SM-F916N': 'Galaxy Z Fold2', 'SM-F900N': 'Galaxy Fold',
            # Galaxy Z Flip
            'SM-F751N': 'Galaxy Z Flip7', 'SM-F761N': 'Galaxy Z Flip7 FE',
            'SM-F741N': 'Galaxy Z Flip6', 'SM-F731N': 'Galaxy Z Flip5', 'SM-F721N': 'Galaxy Z Flip4',
            'SM-F711N': 'Galaxy Z Flip3', 'SM-F700N': 'Galaxy Z Flip',
            # Galaxy A 시리즈
            'SM-A566N': 'Galaxy A56 5G', 'SM-A556N': 'Galaxy A55 5G', 'SM-A546N': 'Galaxy A54 5G',
            'SM-A536N': 'Galaxy A53 5G', 'SM-A528N': 'Galaxy A52s 5G', 'SM-A525N': 'Galaxy A52',
            'SM-A515N': 'Galaxy A51', 'SM-A716N': 'Galaxy A51 5G', 'SM-A715N': 'Galaxy A71',
            'SM-A736N': 'Galaxy A73 5G', 'SM-A725N': 'Galaxy A72 5G',
            'SM-A366N': 'Galaxy A36 5G', 'SM-A356N': 'Galaxy A35 5G', 'SM-A346N': 'Galaxy A34 5G',
            'SM-A336N': 'Galaxy A33 5G', 'SM-A326N': 'Galaxy A32 5G',
            'SM-A266N': 'Galaxy A26 5G', 'SM-A256N': 'Galaxy A25 5G', 'SM-A246N': 'Galaxy A24 5G',
            'SM-A236N': 'Galaxy A23 5G', 'SM-A235F': 'Galaxy A23', 'SM-A226N': 'Galaxy A22 5G',
            'SM-A217N': 'Galaxy A21s', 'SM-A215N': 'Galaxy A21', 'SM-A205N': 'Galaxy A11',
            'SM-A166N': 'Galaxy A16 5G', 'SM-A156N': 'Galaxy A15 5G', 'SM-A146N': 'Galaxy A14 5G',
            'SM-A136N': 'Galaxy A13 5G', 'SM-A125N': 'Galaxy A12',
            'SM-A415N': 'Galaxy A41', 'SM-A315N': 'Galaxy A31',
            'SM-A025N': 'Galaxy A02s', 'SM-A022N': 'Galaxy A01 Core',
            # Galaxy Tab
            'SM-X920N': 'Galaxy Tab S10 Ultra', 'SM-X820N': 'Galaxy Tab S10+', 'SM-X526N': 'Galaxy Tab S10 FE',
            'SM-X910N': 'Galaxy Tab S9 Ultra', 'SM-X810N': 'Galaxy Tab S9+', 'SM-X710N': 'Galaxy Tab S9', 'SM-X510N': 'Galaxy Tab S9 FE',
            'SM-X900N': 'Galaxy Tab S8 Ultra', 'SM-X800N': 'Galaxy Tab S8+', 'SM-X700N': 'Galaxy Tab S8',
            'SM-T990N': 'Galaxy Tab S7+', 'SM-T975N': 'Galaxy Tab S7+', 'SM-T970N': 'Galaxy Tab S7', 'SM-T733N': 'Galaxy Tab S7 FE',
            'SM-X210N': 'Galaxy Tab A9+', 'SM-X200N': 'Galaxy Tab A8', 'SM-T220N': 'Galaxy Tab A7 Lite',
            # Galaxy Z 특수 에디션
            'SM-F99xN': 'Galaxy Z Tri-Fold',
        }
        friendly = {}
        for raw, count in models.items():
            parts = raw.split(' ', 1)
            brand = parts[0] if len(parts) > 1 else ''
            code = parts[1] if len(parts) > 1 else raw
            name = model_names.get(code, f"{brand} {code}".strip())
            friendly[name] = friendly.get(name, 0) + count
        
        sorted_models = sorted(friendly.items(), key=lambda x: -x[1])
        df_models = pd.DataFrame([(k, v) for k, v in sorted_models[:15] if k != 'unknown'], columns=['모델', '대수'])
        fig = px.bar(df_models, x='대수', y='모델', orientation='h', color_discrete_sequence=['#6366F1'])
        fig.update_layout(height=400, margin=dict(t=20, b=20), yaxis={'categoryorder': 'total ascending'})
        st.plotly_chart(fig, use_container_width=True)

# 인기 구간 TOP 10
with route_col:
    st.subheader("🚄 인기 구간 TOP 10")
    routes = data.get('routes', {})
    if routes:
        sorted_routes = sorted(routes.items(), key=lambda x: -x[1])[:10]
        df_routes = pd.DataFrame(sorted_routes, columns=['구간', '티켓 수'])
        fig = px.bar(df_routes, x='티켓 수', y='구간', orientation='h', color_discrete_sequence=['#0052A4'])
        fig.update_layout(height=400, margin=dict(t=20, b=20), yaxis={'categoryorder': 'total ascending'})
        st.plotly_chart(fig, use_container_width=True)

# 열차 종류 분포
train_types = data.get('train_types', {})
if train_types:
    st.subheader("🚆 열차 종류 분포")
    fig = px.pie(names=list(train_types.keys()), values=list(train_types.values()),
                 color_discrete_sequence=px.colors.qualitative.Set2, hole=0.4)
    fig.update_layout(height=250, margin=dict(t=20, b=20, l=20, r=20))
    st.plotly_chart(fig, use_container_width=True)

st.divider()

# ========== 신규 기기 추이 + 제공자별 기기 수 ==========
trend_col, provider_col = st.columns(2)

# 신규 기기 가입 추이
with trend_col:
    st.subheader("📈 신규 기기 가입 추이 (최근 30일)")
    new_daily = data.get('new_device_daily', {})
    if new_daily:
        cutoff = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        filtered = {k: v for k, v in sorted(new_daily.items()) if k >= cutoff}
        if filtered:
            df = pd.DataFrame(list(filtered.items()), columns=['날짜', '신규 기기'])
            fig = px.area(df, x='날짜', y='신규 기기', color_discrete_sequence=['#03C75A'])
            fig.update_layout(height=300, margin=dict(t=20, b=20))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("최근 30일 데이터 없음")

# 로그인 제공자별 평균 기기 수
with provider_col:
    st.subheader("📊 제공자별 평균 기기 수")
    prov_devs = data.get('provider_devices', {})
    if prov_devs:
        prov_stats = []
        for provider, counts in prov_devs.items():
            if provider == 'unknown':
                continue
            avg = sum(counts) / len(counts)
            prov_stats.append({'제공자': provider, '평균 기기 수': round(avg, 1), '사용자 수': len(counts)})
        df_prov = pd.DataFrame(prov_stats)
        fig = px.bar(df_prov, x='제공자', y='평균 기기 수', text='평균 기기 수',
                     color='제공자', color_discrete_map={'kakao': '#FEE500', 'google': '#4285F4', 'naver': '#03C75A'})
        fig.update_layout(height=300, margin=dict(t=20, b=20), showlegend=False)
        fig.update_traces(textposition='outside')
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(df_prov, use_container_width=True, hide_index=True)

st.divider()

# ========== SRT vs KTX 비율 ==========
srt_ktx_col, seat_col = st.columns(2)

with srt_ktx_col:
    st.subheader("🚄 SRT vs KTX 이용 비율")
    train_types_data = data.get('train_types', {})
    if train_types_data:
        srt_count = sum(v for k, v in train_types_data.items() if 'SRT' in k.upper())
        ktx_count = sum(v for k, v in train_types_data.items() if 'KTX' in k.upper() or 'ITX' in k.upper())
        other_count = sum(v for k, v in train_types_data.items() if 'SRT' not in k.upper() and 'KTX' not in k.upper() and 'ITX' not in k.upper())
        srt_ktx = {'SRT': srt_count, 'KTX/ITX': ktx_count}
        if other_count > 0:
            srt_ktx['기타'] = other_count
        fig = px.pie(names=list(srt_ktx.keys()), values=list(srt_ktx.values()),
                     color_discrete_map={'SRT': '#582b52', 'KTX/ITX': '#0052A4', '기타': '#888'},
                     hole=0.4)
        fig.update_layout(height=300, margin=dict(t=20, b=20, l=20, r=20))
        st.plotly_chart(fig, use_container_width=True)

with seat_col:
    st.subheader("💺 좌석 등급 분포")
    seat_data = data.get('seat_classes', {})
    if seat_data:
        fig = px.pie(names=list(seat_data.keys()), values=list(seat_data.values()),
                     color_discrete_sequence=['#0052A4', '#FFC107', '#888'], hole=0.4)
        fig.update_layout(height=300, margin=dict(t=20, b=20, l=20, r=20))
        st.plotly_chart(fig, use_container_width=True)

st.divider()

# ========== 사용자 테이블 ==========
st.subheader("👤 로그인 사용자 목록")
if data['users']:
    df_users = pd.DataFrame(data['users'])
    df_users = df_users[['name', 'email', 'provider', 'devices', 'tickets', 'last_login']].copy()
    # last_login 포맷팅
    def format_login(val):
        if val is None:
            return '-'
        try:
            if hasattr(val, 'timestamp'):
                ts = datetime.fromtimestamp(val.timestamp(), tz=timezone.utc)
            elif isinstance(val, (int, float)):
                ts = datetime.fromtimestamp(val / 1000 if val > 1e12 else val, tz=timezone.utc)
            else:
                return str(val)
            return ts.strftime('%Y-%m-%d %H:%M')
        except Exception:
            return str(val)
    df_users['last_login'] = df_users['last_login'].apply(format_login)
    df_users = df_users.rename(columns={
        'name': '이름', 'email': '이메일', 'provider': '로그인', 'devices': '기기 수', 'tickets': '티켓 수', 'last_login': '최근 로그인'
    }).sort_values('최근 로그인', ascending=False)
    st.dataframe(df_users, use_container_width=True, hide_index=True)

st.divider()

# ========== 컬렉션 요약 ==========
st.subheader("🗄️ Firestore 컬렉션 요약")
summary_data = {
    '컬렉션': ['users', 'device_trials', 'consent_logs', 'email_mappings'],
    '문서 수': [len(data['users']), data['trials_total'], data['consent_total'], data['email_count']],
    '설명': [
        f"소셜 로그인 사용자 (기기 {data['devices_total']}대, 티켓 {data['tickets_total']}건)",
        f"무료 체험 기기 (7일 활성: {data['recent_7d']}, 30일: {data['recent_30d']})",
        f"스마트 예약 동의 (동의: {data['consent_agreed']}, 미동의: {data['consent_total'] - data['consent_agreed']})",
        "소셜 로그인 이메일 매핑"
    ]
}
st.dataframe(pd.DataFrame(summary_data), use_container_width=True, hide_index=True)

# 푸터
st.caption("🚄 RailPick Admin Dashboard | Firestore (railpick) | 데이터 5분 캐시")
