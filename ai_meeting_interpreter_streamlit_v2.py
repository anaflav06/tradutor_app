# -*- coding: utf-8 -*-
"""AI Meeting Interpreter - Streamlit V2 (mobile-friendly).
Instalacao: python -m pip install -r requirements.txt
Executar: python -m streamlit run ai_meeting_interpreter_streamlit_v1.py
Streamlit Community Cloud: app file + requirements.txt (renomear para requirements.txt no repositorio)
Chave: .streamlit/secrets.toml => OPENAI_API_KEY = "..." (nunca publicar no GitHub).
"""
import base64
import io
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components
from openai import OpenAI

st.set_page_config(page_title="Intérprete de Reuniões", page_icon="🎧", layout="wide", initial_sidebar_state="collapsed")

BLUE = "#1658B8"
TECH = "CAN, LIN, UDS, ECU, DTC, infotainment, cluster, telecoding, variant coding, flashing, firmware, gateway, Stellantis, Testrack, bench, diagnostic session"

st.markdown("""
<style>
.stApp {background:#f5f8fe;color:#172b4d}
.block-container {max-width:1180px; padding-top:1.25rem; padding-bottom:3rem}
h1,h2,h3 {color:#143b78}
h1 {letter-spacing:-.035em}
[data-testid="stMetric"] {background:#fff;border:1px solid #e3ebf6;border-radius:16px;padding:14px}
div.stButton>button[kind="primary"] {background:#1766c1;color:white;border-radius:13px;min-height:48px;font-weight:700}
div.stButton>button {border-radius:13px;min-height:45px;font-weight:650}
[data-testid="stTextArea"] textarea {border-radius:14px!important;font-size:1.06rem}
[data-testid="stTextInput"] input {border-radius:12px!important}
.hero {background:linear-gradient(110deg,#102e5c,#1766c1);padding:23px 27px;border-radius:21px;color:#fff;margin-bottom:16px}
.hero h1 {color:#fff;margin:0;font-size:1.8rem}
.hero p {color:#dfedff;margin:7px 0 0}
.card {background:white;border:1px solid #e4edf8;padding:15px 18px;border-radius:16px;margin-bottom:12px}
.bigtxt {font-size:1.17rem;line-height:1.55}
.small {color:#59708d;font-size:.91rem}
@media(max-width:640px){.hero{padding:18px}.hero h1{font-size:1.45rem}}
</style>
""", unsafe_allow_html=True)

# Component Streamlit simples, sem bibliotecas JS externas. O áudio fica no navegador
# ate o envio de cada bloco ao servidor para transcricao.
CAPTURE_HTML = r'''<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8"/><style>
body{font:15px system-ui,-apple-system,Segoe UI,sans-serif;margin:0;padding:6px;color:#203b60}
#panel{padding:12px;background:#f0f6ff;border:1px solid #dce8fa;border-radius:15px}
button{border:0;border-radius:12px;padding:13px 17px;font-size:15px;font-weight:700;cursor:pointer;margin-right:8px;margin-bottom:8px}
#start{background:#1764bd;color:white}#stop{background:#fff;color:#bb3042;border:1px solid #e4a2ac}
#status{font-size:14px;color:#4d637e;margin-top:6px}#hint{font-size:12px;color:#60758e;margin-top:7px}
</style></head><body><div id="panel"><button id="start">▶ Iniciar escuta</button><button id="stop" disabled>■ Parar</button><div id="status">Pronto para começar.</div><div id="hint"></div></div>
<script>
const mode = '__MODE__';
const start = document.getElementById('start'), stop = document.getElementById('stop'), status = document.getElementById('status'), hint = document.getElementById('hint');
const parentMsg = (type, data={}) => window.parent.postMessage({isStreamlitMessage:true,type,...data},'*');
parentMsg('streamlit:componentReady',{apiVersion:1}); parentMsg('streamlit:setFrameHeight',{height:150});
let stream=null, recorder=null, seq=0, active=false, ticker=null, stopping=false, mimeChoice=null;
hint.textContent = mode==='tab' ? 'No seletor do navegador, escolha a ABA do Teams/Meet e marque “Compartilhar áudio da guia”.' : 'Autorize o microfone quando o navegador solicitar.';
window.addEventListener('message',e=>{if(e.data && e.data.type==='streamlit:render')parentMsg('streamlit:setFrameHeight',{height:150})});
const emit=async(blob)=>{
 if(blob.size<1200)return;
 const data=await new Promise((resolve,reject)=>{let r=new FileReader();r.onload=()=>resolve(r.result);r.onerror=reject;r.readAsDataURL(blob)});
 parentMsg('streamlit:setComponentValue',{value:{id:mode+'-'+(++seq)+'-'+Date.now(),kind:mode,audio:data.split(',')[1],mime:blob.type||'audio/webm'},dataType:'json'});
};
start.onclick=async()=>{
 try{
  if(mode==='tab'){
   if(!navigator.mediaDevices.getDisplayMedia)throw Error('Este navegador não permite capturar o áudio da aba. Use Edge ou Chrome no computador.');
   stream=await navigator.mediaDevices.getDisplayMedia({video:true,audio:true});
   if(!stream.getAudioTracks().length){stream.getTracks().forEach(t=>t.stop());throw Error('Nenhum áudio foi compartilhado. Marque a opção de compartilhar áudio da aba.');}
  } else {stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true},video:false})}
  mimeChoice=['audio/webm;codecs=opus','audio/webm','audio/mp4'].find(x=>MediaRecorder.isTypeSupported(x));
  active=true;stopping=false;start.disabled=true;stop.disabled=false;
  const newChunk=()=>{
    if(!active)return;
    const rec=mimeChoice?new MediaRecorder(stream,{mimeType:mimeChoice}):new MediaRecorder(stream);
    recorder=rec;
    rec.ondataavailable=e=>{if(e.data && e.data.size)emit(e.data).catch(console.error)};
    rec.onerror=e=>{status.textContent='Erro de gravação: '+(e.error?.message||'desconhecido')};
    rec.start();
  };
  newChunk();
  ticker=setInterval(()=>{
    if(!active || !recorder || recorder.state!=='recording')return;
    const previous=recorder;
    previous.stop(); // Cada parte é um arquivo de áudio independente e completo.
    newChunk();
  },mode==='reply'?10000:6500);
  stream.getTracks().forEach(t=>t.onended=()=>finish());
  status.textContent=mode==='tab'?'🔴 Captando o áudio da aba. Legendas aparecem em blocos.': '🔴 Ouvindo pelo microfone.';
 }catch(e){status.textContent='⚠️ '+(e.message||String(e));}
};
function finish(){
 if(stopping)return;
 stopping=true;active=false;clearInterval(ticker);
 if(recorder?.state==='recording')recorder.stop();
 stream?.getTracks().forEach(t=>{t.onended=null;t.stop()});
 start.disabled=false;stop.disabled=true;status.textContent='Escuta encerrada.';
}
stop.onclick=finish;
</script></body></html>'''

@st.cache_resource
def components_ready():
    directory = Path(tempfile.mkdtemp(prefix="interpreter_components_"))
    for mode in ("tab", "mic", "reply"):
        p = directory / mode
        p.mkdir(exist_ok=True)
        (p / "index.html").write_text(CAPTURE_HTML.replace("__MODE__", mode), encoding="utf-8")
    return {
        mode: components.declare_component("interpreter_" + mode, path=str(directory / mode))
        for mode in ("tab", "mic", "reply")
    }

for k, default in {
    "history": [], "last_events": [], "last_reply": "", "last_pt": "",
    "reply_input": "", "message": "", "key_text": "", "capturing": False
}.items():
    if k not in st.session_state:
        st.session_state[k] = default


def load_key():
    try:
        secret = st.secrets.get("OPENAI_API_KEY", "")
    except Exception:
        secret = ""
    return secret or os.environ.get("OPENAI_API_KEY", "") or st.session_state.key_text


def client():
    key = load_key().strip()
    return OpenAI(api_key=key, timeout=35) if key else None


def translate(text, direction):
    cli = client()
    if cli is None:
        raise ValueError("Configure uma chave da API OpenAI para ativar a tradução.")
    target = "português brasileiro" if direction == "en_pt" else "inglês profissional simples e natural"
    instruction = (
        "Você é intérprete de reuniões técnicas de engenharia automotiva. "
        f"Traduza fielmente para {target}, sem acrescentar informações, explicações ou comentários. "
        f"Preserve siglas e nomenclatura técnica ({TECH}). "
        "Se for uma frase incompleta, traduza somente o que estiver presente. "
        "Retorne SOMENTE a tradução."
    )
    response = cli.chat.completions.create(
        model="gpt-4.1-mini", temperature=0.1,
        messages=[{"role":"system","content":instruction},{"role":"user","content":text}],
    )
    return (response.choices[0].message.content or "").strip()


def transcribe(audio_bytes, name, language):
    cli = client()
    if cli is None:
        raise ValueError("Configure uma chave da API OpenAI para ativar a transcrição.")
    fileobj = io.BytesIO(audio_bytes)
    fileobj.name = name
    r = cli.audio.transcriptions.create(
        model="gpt-transcribe", file=fileobj, language=language,
        prompt=f"Technical meeting terminology: {TECH}." if language == "en" else None
    )
    return (r.text or "").strip()


def add_history(kind, original, translation):
    if not original.strip():
        return
    st.session_state.history.append({"time":datetime.now().strftime("%H:%M:%S"),"kind":kind,
                                     "original":original.strip(),"translation":translation.strip()})
    st.session_state.history = st.session_state.history[-150:]


def consume_event(event, channel):
    if not isinstance(event, dict) or not event.get("audio"):
        return
    event_id = event.get("id")
    if event_id in st.session_state.last_events:
        return
    st.session_state.last_events = (st.session_state.last_events + [event_id])[-40:]
    if not client():
        st.warning("Configure a chave da API antes de começar.")
        return
    try:
        data = base64.b64decode(event["audio"], validate=True)
        if len(data) < 1300:
            return
        ext = ".mp4" if "mp4" in event.get("mime","") else ".webm"
        with st.spinner("🎧 Interpretando o trecho de áudio..."):
            language = "pt" if channel == "reply" else "en"
            original = transcribe(data, "trecho"+ext, language)
            if not original or original.strip().lower() in {"thank you.","thanks.","obrigado.","legendas pela comunidade amara.org"}:
                return
            translated = translate(original, "pt_en" if channel == "reply" else "en_pt")
            if channel == "reply":
                st.session_state.last_reply = translated
                st.session_state.last_pt = original
            add_history("Sua resposta" if channel == "reply" else "Reunião", original, translated)
    except Exception as exc:
        st.error(f"Não foi possível processar o áudio: {exc}")


def text_translate(text):
    text = text.strip()
    if not text:
        st.info("Digite uma frase em português.")
        return
    try:
        with st.spinner("Traduzindo sua resposta..."):
            translated = translate(text, "pt_en")
        st.session_state.last_pt = text
        st.session_state.last_reply = translated
        add_history("Sua resposta", text, translated)
    except Exception as exc:
        st.error(str(exc))


st.markdown('<div class="hero"><h1>🎧 Intérprete de Reuniões</h1><p>Entenda a reunião em português • Responda em inglês • Tudo em uma tela</p></div>', unsafe_allow_html=True)

with st.expander("⚙️ Configuração inicial — abrir somente na primeira vez", expanded=not bool(load_key())):
    if load_key():
        st.success("✅ Chave da API configurada. Você pode começar.")
    else:
        st.info("Para transcrever e traduzir, é necessário conectar uma chave da API OpenAI. A assinatura do ChatGPT não inclui os custos da API.")
        st.text_input("Cole sua chave da API (para teste local)", type="password", key="key_text", help="No Streamlit Cloud, configure OPENAI_API_KEY em App Settings → Secrets; nunca coloque a chave no GitHub.")
        st.caption("Para publicar, salve OPENAI_API_KEY nos Secrets da sua aplicação. O campo acima é apenas para testes na sessão atual.")
    st.caption("🔒 Informe a todos que a reunião está sendo processada por uma ferramenta de IA. Cada trecho de áudio é enviado à API para transcrição.")

st.markdown("### 1 · Entender a reunião")
st.write("**No celular:** toque em **Gravar fala em inglês**, autorize o microfone e grave um trecho. Depois toque em **Traduzir áudio**.")
recorded_meeting = st.audio_input("🎙️ Gravar fala em inglês", key="mobile_meeting_audio")
if recorded_meeting is not None:
    st.caption("Áudio gravado. Clique abaixo para obter a legenda em português.")
    if st.button("🇧🇷 Traduzir áudio para português", type="primary", use_container_width=True, key="translate_meeting_audio"):
        consume_event({"id":"meeting-"+str(hash(recorded_meeting.getvalue())),
                       "audio":base64.b64encode(recorded_meeting.getvalue()).decode(),
                       "mime":"audio/wav"}, "meeting")
with st.expander("💻 No computador: tentar escuta automática (experimental)"):
    st.warning("A captura contínua funciona apenas em navegadores e dispositivos compatíveis. No celular, use o gravador acima. No Teams instalado no computador, o navegador não consegue capturar diretamente o áudio do aplicativo.")
    source = st.radio("Fonte de áudio", ["🔊 Áudio de uma aba do navegador", "🎙️ Microfone"], key="desktop_source")
    mode = "tab" if "aba" in source else "mic"
    if mode == "tab":
        st.caption("Ao iniciar, escolha a aba da reunião e habilite 'Compartilhar áudio da guia'.")
    else:
        st.caption("Permita acesso ao microfone. Se a reunião estiver no fone, o microfone não ouvirá os participantes.")
    try:
        capture = components_ready()[mode](key="desktop_capture_"+mode, default=None)
        consume_event(capture, mode)
    except Exception as exc:
        st.error(f"Captura indisponível: {exc}")
with st.expander("📁 Enviar arquivo de áudio já gravado"):
    uploaded = st.file_uploader("Selecione um arquivo", type=["wav","mp3","m4a","mp4","webm","ogg"], key="meeting_upload")
    if uploaded is not None and st.button("Traduzir arquivo", use_container_width=True):
        try:
            with st.spinner("Traduzindo..."):
                original = transcribe(uploaded.getvalue(), uploaded.name, "en")
                translated = translate(original, "en_pt")
                add_history("Reunião", original, translated)
        except Exception as exc:
            st.error(str(exc))
st.markdown("**🇧🇷 Legenda mais recente**")
items = [x for x in st.session_state.history if x["kind"] == "Reunião"]
if items:
    item = items[-1]
    st.markdown('<div class="card"><div class="small">'+item["time"]+' · Tradução</div><div class="bigtxt">'+__import__('html').escape(item["translation"])+"</div></div>", unsafe_allow_html=True)
    with st.expander("Ver original em inglês"):
        st.write(item["original"])
else:
    st.info("A tradução aparecerá aqui depois da primeira gravação.")

st.divider()
st.markdown("### 2 · Minha resposta em inglês")
st.write("Você pode **digitar em português** ou **falar pelo microfone**. A resposta aparecerá escrita em inglês para você ler na reunião.")
left, right = st.columns([1,1],gap="large")
with left:
    reply_text = st.text_area("✍️ Escreva sua resposta em português", height=118, key="reply_input", placeholder="Ex.: Podemos repetir o teste amanhã, quando tivermos o software correto?")
    if st.button("🌐 Traduzir para inglês", type="primary", use_container_width=True):
        text_translate(reply_text)
    st.markdown("**🎙️ Ou prefira falar em português:**")
    spoken = st.audio_input("Gravar minha resposta", key="mobile_reply_audio")
    if spoken is not None and st.button("🇺🇸 Traduzir minha gravação para inglês", use_container_width=True):
        consume_event({"id":"reply-"+str(hash(spoken.getvalue())),
                       "audio":base64.b64encode(spoken.getvalue()).decode(),
                       "mime":"audio/wav"}, "reply")
with right:
    st.markdown("**🇺🇸 Sua frase pronta para falar**")
    if st.session_state.last_reply:
        st.text_area("Tradução em inglês", value=st.session_state.last_reply, height=135, label_visibility="collapsed")
        st.caption("Selecione e copie o texto acima para usar durante a reunião.")
        if st.session_state.last_pt:
            st.caption("Original: " + st.session_state.last_pt)
    else:
        st.markdown('<div class="card"><div class="small">Sua tradução aparecerá aqui</div><div class="bigtxt">I can help you with that. 😊</div><div class="small">Exemplo ilustrativo, não uma resposta enviada.</div></div>', unsafe_allow_html=True)

st.divider()
st.markdown("### 3 · Histórico da reunião")
if st.session_state.history:
    with st.container(height=270):
        for entry in reversed(st.session_state.history):
            flag = "🇧🇷" if entry["kind"] == "Reunião" else "🇺🇸"
            st.markdown(f"**{flag} {entry['kind']} · {entry['time']}**")
            st.write(entry["translation"])
            with st.expander("Ver frase original"):
                st.write(entry["original"])
            st.divider()
    lines = ["AI MEETING INTERPRETER - HISTORICO", ""]
    for x in st.session_state.history:
        lines += [f"[{x['time']}] {x['kind']}", "Original: " + x["original"], "Traducao: " + x["translation"], ""]
    a,b = st.columns(2)
    with a:
        st.download_button("⬇️ Baixar histórico", "\n".join(lines), file_name="reuniao_traduzida.txt", mime="text/plain", use_container_width=True)
    with b:
        if st.button("🗑️ Limpar histórico", use_container_width=True):
            st.session_state.history=[]
            st.session_state.last_reply=""
            st.session_state.last_pt=""
            st.rerun()
else:
    st.caption("As traduções desta sessão ficam aqui. Você poderá baixar o histórico antes de fechar a página.")

st.caption("Versão V2 • No celular, gravação por trechos; no computador, captura experimental em blocos, não simultânea palavra por palavra • A qualidade depende do áudio, da rede e da API • Não grava reuniões permanentemente no servidor.")
