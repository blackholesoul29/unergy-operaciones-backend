#!/usr/bin/env python3
"""
Descarga fallas-unergy/index.html desde GitHub y lo adapta para usar
el backend FastAPI de Plataforma Operaciones en lugar de Google Apps Script.

Uso:
    cd backend
    python scripts/patch_monitoreo.py

El resultado se guarda en:
    backend/static/monitoreo/index.html
"""
import urllib.request
import re
import sys
from pathlib import Path

GITHUB_RAW = "https://raw.githubusercontent.com/laurah-cloud/fallas-unergy/main/index.html"
OUTPUT_PATH = Path(__file__).parent.parent / "static" / "monitoreo" / "index.html"

# ─────────────────────────────────────────────────────────────────────────────
# Bloque de integración que se inyecta al inicio del <script>
# ─────────────────────────────────────────────────────────────────────────────
BRIDGE_JS = r"""
/* ═══════════════ PLATAFORMA OPERACIONES BRIDGE ═══════════════
   Este bloque reemplaza Google Apps Script por el backend FastAPI.
   NO EDITAR MANUALMENTE — regenerar con scripts/patch_monitoreo.py
   ═══════════════════════════════════════════════════════════════ */
var _API_TOKEN = null;
var _PLATFORM_USER = null;
var _PLATFORM_MODE = false;

(function initPlatformAuth() {
  var params = new URLSearchParams(window.location.search);
  var token = params.get('token');
  if (!token) return;
  _API_TOKEN = token;
  _PLATFORM_MODE = true;
  try {
    var b64 = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
    var pad = b64.padEnd(b64.length + (4 - b64.length % 4) % 4, '=');
    var payload = JSON.parse(atob(pad));
    _PLATFORM_USER = {
      email: payload.email || '',
      nombre: payload.nombre || payload.email || 'Usuario',
      rol: payload.rol || 'monitor',
      id: payload.sub
    };
  } catch(e) {
    console.warn('[Bridge] Token inválido:', e);
  }
})();

/* helper fetch con auth */
function _apiFetch(method, path, body) {
  var opts = { method: method, headers: { 'Content-Type': 'application/json' } };
  if (_API_TOKEN) opts.headers['Authorization'] = 'Bearer ' + _API_TOKEN;
  if (body !== undefined) opts.body = JSON.stringify(body);
  return fetch(path, opts).then(function(r) {
    if (r.status === 401) {
      toast('⚠ Sesión expirada. Recarga la plataforma.', 8000);
      throw new Error('401');
    }
    if (!r.ok) throw new Error('API ' + r.status);
    return r.json();
  });
}

/* auto-skip login si venimos desde la plataforma */
document.addEventListener('DOMContentLoaded', function() {
  if (!_PLATFORM_MODE || !_PLATFORM_USER) return;
  var overlay = document.getElementById('login-ov');
  if (overlay) overlay.className = '';          /* ocultar overlay */
  var user = _PLATFORM_USER;
  pendingEmail = user.email;
  /* simular sesión de monitor para que applyRole() funcione */
  saveSession('monitor', user.email, user.nombre, []);
  try { applyRole(); } catch(e) {}
  /* cargar datos */
  loadCatalog();
  loadFaults();
});
/* ════════════════════════════════════════════════════════════════ */
"""

# ─────────────────────────────────────────────────────────────────────────────
# Reemplazos de funciones clave
# ─────────────────────────────────────────────────────────────────────────────

NEW_LOAD_FAULTS = r"""function loadFaults(){
  setSync("spin","Sincronizando…");
  _apiFetch('GET','/api/v1/monitoreo/fallas').then(function(res){
    if(res&&res.ok&&res.faults){
      faults=res.faults;
      faults.forEach(function(f){
        var n=parseInt((f.id||"").replace(/^FAL?-?\d*-?/,"").replace(/\D/g,""));
        if(!isNaN(n)&&n>=idN)idN=n+1;
      });
    }
    setSync("ok","Sincronizado ✓");hideLoader();renderAll();
    toast("✓ "+faults.length+" fallas cargadas");
  }).catch(function(e){
    setSync("err","Sin conexión");hideLoader();renderAll();
    toast("⚠ Error al cargar: "+e.message);
  });
}"""

NEW_SERVER_SAVE = r"""function serverSave(f,cb){
  setSync("spin","Guardando…");
  var fdd=fd(f.code)||{};
  var cleanRes=(f.res&&f.res.trim()&&f.res.length>3&&!/^\d/.test(f.res)&&
    !f.res.includes("/")&&!f.res.includes("GMT"))?f.res:"";
  var payload={
    id:f.id,project:f.proj,faultCode:f.code,
    faultLabel:fdd.label||f.faultLabel||f.code,
    categoryId:fdd.catId||"1",
    statusLbl:ST[f.st]?ST[f.st].lbl:f.st,status:f.st,
    identDate:fmtD(f.date),identTime:padT(f.time),
    occTime:toSheets(f.occ),resType:cleanRes,
    desc:f.desc||"",followUp:f.flw||"",
    driveUrl:f.driveUrl||"",driveUrls:f.driveUrls||[],
    endTime:toSheets(f.endDT),
    centinela:f.centinela||"",prioridad:f.prio||"media",
    notify:f.notify===true
  };
  _apiFetch('POST','/api/v1/monitoreo/fallas/save',payload).then(function(r){
    setSync(r&&r.ok?"ok":"err",r&&r.ok?"Guardado ✓":"Error al guardar");
    if(r&&r.fault){
      /* actualizar falla en memoria local */
      var idx=faults.findIndex(function(x){return x.id===f.id||x.id===(r.fault&&r.fault.id);});
      if(idx>=0)faults[idx]=r.fault; else if(r.fault)faults.unshift(r.fault);
    }
    if(cb)cb(r&&r.ok);
  }).catch(function(e){
    setSync("err","Error de red");
    toast("⚠ No se pudo guardar: "+e.message);
    if(cb)cb(false);
  });
}"""

NEW_SERVER_DEL = r"""function serverDel(id){
  _apiFetch('POST','/api/v1/monitoreo/fallas/delete',{id:id}).then(function(r){
    setSync(r&&r.ok?"ok":"err",r&&r.ok?"Eliminado ✓":"Error al eliminar");
  }).catch(function(e){
    setSync("err","Error");
    toast("⚠ No se pudo eliminar: "+e.message);
  });
}"""

NEW_LOAD_CATALOG = r"""function loadCatalog(){
  var lsub=document.getElementById("lsub");
  if(lsub)lsub.textContent="Cargando catálogo…";
  _apiFetch('GET','/api/v1/monitoreo/catalogo').then(function(cats){
    if(Array.isArray(cats)&&cats.length){
      FAULT_DESCS={};FAULT_AFECTA={};
      cats.forEach(function(cat){
        (cat.faults||[]).forEach(function(ft){
          if(ft.code){
            if(ft.desc)FAULT_DESCS[ft.code]=ft.desc;
            if(ft.afecta)FAULT_AFECTA[ft.code]=ft.afecta;
          }
        });
      });
      /* reconstruir DEFAULT_CATS con datos de la BD */
      DEFAULT_CATS=cats.map(function(c){
        return{id:c.id,lbl:c.lbl,ico:c.ico,col:c.col,
          faults:(c.faults||[]).map(function(f){return{code:f.code,label:f.label};})};
      });
      rebuildF();updateFcatFilter();CATALOG_READY=true;
      toast("✓ Catálogo actualizado",2000);
    }
  }).catch(function(e){
    console.warn("Catálogo no disponible:",e);
    rebuildF();updateFcatFilter();
    toast("⚠ Catálogo no disponible",5000);
  });
}"""

NEW_LOGIN_EMAIL_GO = r"""function loginEmailGo(){
  var email=(document.getElementById("li-email").value||"").trim().toLowerCase();
  var err=document.getElementById("li-email-err");
  if(!email||email.indexOf("@")<0){err.textContent="⚠ Ingresa un correo válido";return;}
  err.textContent="";pendingEmail=email;
  if(isMonitorEmail(email)){
    /* usuarios @unergy: verificar contra la plataforma */
    showLoginStep("loading");
    _apiFetch('POST','/api/v1/monitoreo/auth/verify-email',{email:email}).then(function(r){
      if(r&&r.ok){
        saveSession('monitor',email,r.nombre||email,[]);
        document.getElementById("login-ov").className="";
        applyRole();loadFaults();
      } else {
        showLoginStep("email");
        err.textContent="⚠ Correo no registrado en la plataforma.";
      }
    }).catch(function(){showLoginStep("email");err.textContent="⚠ Sin conexión con el servidor.";});
  } else {
    /* clientes externos: enviar código */
    showLoginStep("loading");
    _apiFetch('POST','/api/v1/monitoreo/auth/send-code',{email:email}).then(function(r){
      if(r&&r.ok){
        var em=document.getElementById("ls-code-em");if(em)em.textContent=email;
        var ci=document.getElementById("li-code");if(ci)ci.value="";
        var ce=document.getElementById("li-code-err");if(ce)ce.textContent="";
        showLoginStep("code");
        setTimeout(function(){var el=document.getElementById("li-code");if(el)el.focus();},80);
      } else {
        showLoginStep("email");err.textContent="⚠ Correo no registrado.";
      }
    }).catch(function(){showLoginStep("email");err.textContent="⚠ Sin conexión con el servidor.";});
  }
}"""

NEW_LOGIN_CODE_GO = r"""function loginCodeGo(){
  var code=(document.getElementById("li-code").value||"").trim();
  var err=document.getElementById("li-code-err");
  if(code.length!==6||!/^\d{6}$/.test(code)){err.textContent="⚠ Ingresa el código de 6 dígitos";return;}
  err.textContent="";showLoginStep("loading");
  _apiFetch('POST','/api/v1/monitoreo/auth/verify-code',{email:pendingEmail,code:code}).then(function(r){
    if(r&&r.ok){
      saveSession('cliente',pendingEmail,"",r.projects||[]);
      document.getElementById("login-ov").className="";
      applyRole();
      if(!r.projects||r.projects.length===0){
        toast("⚠ Tu cuenta no tiene proyectos asignados.",6000);
        hideLoader();renderAll();
      } else {
        toast("✓ Acceso concedido",3000);loadFaults();
      }
    } else {
      showLoginStep("code");err.textContent="⚠ Código incorrecto o expirado";
    }
  }).catch(function(){showLoginStep("code");err.textContent="⚠ Sin conexión.";});
}"""


def _find_function_end(js: str, start_idx: int) -> int:
    """Encuentra el índice del cierre de la función (balance de llaves)."""
    depth = 0
    i = start_idx
    found_open = False
    while i < len(js):
        c = js[i]
        if c == '{':
            depth += 1
            found_open = True
        elif c == '}':
            depth -= 1
            if found_open and depth == 0:
                return i + 1
        i += 1
    return len(js)


def _replace_function(js: str, signature: str, replacement: str) -> tuple[str, bool]:
    """Reemplaza una función completa buscando su firma y balanceando llaves."""
    idx = js.find(signature)
    if idx == -1:
        return js, False
    end_idx = _find_function_end(js, idx)
    return js[:idx] + replacement + js[end_idx:], True


def patch(html: str) -> str:
    # 1. Inyectar bridge justo después de la primera etiqueta <script>
    # Buscamos el primer <script> que no sea de una librería externa
    first_script = html.find("<script>")
    if first_script == -1:
        first_script = html.find("<script ")
    if first_script != -1:
        # insertar después del cierre del tag de apertura
        close_tag = html.index(">", first_script) + 1
        html = html[:close_tag] + "\n" + BRIDGE_JS + html[close_tag:]
        print("[patch] OK Bridge JS inyectado")
    else:
        print("[patch] FAIL No se encontro <script>")

    # 2. Reemplazar funciones API de Google Apps Script
    replacements = [
        ("function loadFaults()", NEW_LOAD_FAULTS),
        ("function serverSave(", NEW_SERVER_SAVE),
        ("function serverDel(", NEW_SERVER_DEL),
        ("function loadCatalog()", NEW_LOAD_CATALOG),
        ("function loginEmailGo()", NEW_LOGIN_EMAIL_GO),
        ("function loginCodeGo()", NEW_LOGIN_CODE_GO),
    ]

    # Extraer solo la parte JS del HTML para hacer reemplazos más seguros
    # Trabajamos sobre el HTML completo pero los reemplazos son únicos
    for sig, new_fn in replacements:
        html, found = _replace_function(html, sig, new_fn)
        status = "OK" if found else "FAIL"
        print(f"[patch] {status} {sig[:40]}")

    # 3. Deshabilitar las funciones apiGet/apiPost originales (ya no se usan)
    old_api_get_marker = "function apiGet(p,timeout){"
    if old_api_get_marker in html:
        html, _ = _replace_function(
            html,
            old_api_get_marker,
            "function apiGet(p,timeout){ return _apiFetch('GET', '/api/v1/monitoreo/_legacy?action='+(p.action||''), p); }"
        )
        print("[patch] OK apiGet neutralizada")

    old_api_post_marker = "function apiPost(body){"
    if old_api_post_marker in html:
        html, _ = _replace_function(
            html,
            old_api_post_marker,
            "function apiPost(body){ return _apiFetch('POST', '/api/v1/monitoreo/_legacy', body); }"
        )
        print("[patch] OK apiPost neutralizada")

    # 4. Eliminar SCRIPT_URL hardcodeado (por seguridad)
    html = re.sub(
        r'var SCRIPT_URL="https://script\.google\.com/[^"]*"',
        'var SCRIPT_URL="" /* neutralizado por bridge */',
        html
    )
    print("[patch] OK SCRIPT_URL neutralizada")

    # 5. Meta charset y base tag para rutas relativas
    if '<base href' not in html:
        html = html.replace('<head>', '<head>\n  <base href="/">', 1)
        print("[patch] OK <base href> anadido")

    return html


def main():
    print(f"Descargando {GITHUB_RAW} ...")
    try:
        req = urllib.request.Request(
            GITHUB_RAW,
            headers={"User-Agent": "Mozilla/5.0 patch_monitoreo.py"}
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8")
    except Exception as e:
        print(f"ERROR descargando: {e}")
        sys.exit(1)

    print(f"Descargado {len(html):,} caracteres")
    patched = patch(html)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(patched, encoding="utf-8")
    print(f"\nGuardado en {OUTPUT_PATH}")
    print(f"   Tamano: {len(patched):,} caracteres")
    print("\nProximos pasos:")
    print("  1. Reinicia el backend (Railway o local)")
    print("  2. Accede a {BACKEND_URL}/monitoreo?token=<jwt>")


if __name__ == "__main__":
    main()
