import requests
from bs4 import BeautifulSoup
import re
from typing import Dict, List, Optional
from urllib.parse import urlparse
from .logger import logger

class SiteAnalyzer:
    def __init__(self, url: str):
        self.url = url if url.startswith("http") else f"https://{url}"
        self.headers_analysis = {}
        self.html_analysis = {}
        self.app_type_inference = "Unknown"
        self.findings = []

    def analyze(self) -> Dict:
        """Realiza el análisis completo del sitio."""
        logger.info(f"Iniciando análisis de sitio: {self.url}")
        try:
            response = requests.get(self.url, timeout=30, allow_redirects=True)
            self._analyze_headers(response.headers)
            self._analyze_html(response.text)
            self._infer_app_type(response.text, response.headers)
            
            return {
                "headers": self.headers_analysis,
                "html": self.html_analysis,
                "app_type": self.app_type_inference,
                "findings": self.findings
            }
        except requests.RequestException as e:
            logger.error(f"Error al conectar con {self.url}: {e}")
            self.findings.append(f"CRITICAL: Failed to connect to {self.url}: {e}")
            return {}

    def _analyze_headers(self, headers: requests.structures.CaseInsensitiveDict):
        """Analiza las cabeceras HTTP."""
        logger.info("Analizando cabeceras HTTP...")
        
        # Server
        server = headers.get("Server", "Unknown")
        self.headers_analysis["Server"] = server
        if server != "Unknown":
            self.findings.append(f"Server detected: {server}")

        # Backend Tech (X-Powered-By)
        x_powered_by = headers.get("X-Powered-By")
        if x_powered_by:
            self.headers_analysis["Backend"] = x_powered_by
            self.findings.append(f"Backend Technology detected: {x_powered_by}")
        
        # Security Headers
        security_headers = ["Content-Security-Policy", "X-Frame-Options", "Strict-Transport-Security", "X-Content-Type-Options"]
        found_security = {h: headers.get(h) for h in security_headers if headers.get(h)}
        self.headers_analysis["Security Headers"] = found_security
        if found_security:
            self.findings.append(f"Security Headers present: {', '.join(found_security.keys())}")

        # Cloudflare / CDN
        if "cf-ray" in headers or "cloudflare" in str(headers.get("Server", "")).lower():
            self.headers_analysis["CDN"] = "Cloudflare"
            self.findings.append("CDN detected: Cloudflare")

    def _analyze_html(self, html_content: str):
        """Analiza el contenido HTML."""
        logger.info("Analizando contenido HTML...")
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # CSS Frameworks
        css_frameworks = []
        links = soup.find_all('link', rel='stylesheet')
        for link in links:
            href = link.get('href', '')
            if 'bootstrap' in href:
                css_frameworks.append("Bootstrap")
            elif 'tailwind' in href:
                css_frameworks.append("Tailwind CSS")
            elif 'bulma' in href:
                css_frameworks.append("Bulma")
            elif 'foundation' in href:
                css_frameworks.append("Foundation")
        
        self.html_analysis["CSS Frameworks"] = list(set(css_frameworks))
        if css_frameworks:
            self.findings.append(f"CSS Frameworks detected: {', '.join(set(css_frameworks))}")

        # JS Libraries / Frameworks
        js_frameworks = []
        scripts = soup.find_all('script')
        html_str = html_content.lower()
        
        # Check script src
        for script in scripts:
            src = script.get('src', '')
            if 'jquery' in src:
                js_frameworks.append("jQuery")
            if 'react' in src or 'react-dom' in src:
                js_frameworks.append("React")
            if 'vue' in src:
                js_frameworks.append("Vue.js")
            if 'angular' in src:
                js_frameworks.append("Angular")
            if 'moment' in src:
                js_frameworks.append("Moment.js")

        # Check inpage patterns
        if "react-root" in html_str or "_reactroot" in html_str:
            js_frameworks.append("React (Detected via DOM)")
        if "vue-app" in html_str or "__vue__" in html_str:
            js_frameworks.append("Vue.js (Detected via DOM)")
        if "ng-app" in html_str:
            js_frameworks.append("Angular (Detected via DOM)")
        
        self.html_analysis["JS Frameworks"] = list(set(js_frameworks))
        if js_frameworks:
            self.findings.append(f"JS Libraries/Frameworks detected: {', '.join(set(js_frameworks))}")

        # Forms & Security Tokens
        forms = soup.find_all('form')
        token_names = ['csrf', 'csrf_token', '_token', 'authenticity_token']
        found_tokens = []
        for form in forms:
            inputs = form.find_all('input')
            for inp in inputs:
                name = inp.get('name', '').lower()
                if any(token in name for token in token_names):
                    found_tokens.append(name)
        
        self.html_analysis["Form Tokens"] = list(set(found_tokens))
        if found_tokens:
            self.findings.append(f"Potential CSRF Tokens found: {', '.join(set(found_tokens))}")

    def _infer_app_type(self, html: str, headers: dict):
        """Intenta inferir el tipo de aplicación."""
        app_type = "Static Site / Server Rendered"
        
        # SPA Indicators
        spa_indicators = ["<div id=\"root\"></div>", "<div id=\"app\"></div>", "window.initialState"]
        if any(ind in html for ind in spa_indicators):
            app_type = "Single Page Application (SPA)"
        
        # SSR Indicators (header check often helps too, e.g. X-Powered-By: Next.js)
        if "next.js" in str(headers.get("X-Powered-By", "")).lower():
            app_type = "Server-Side Rendering (Next.js)"
        
        self.app_type_inference = app_type
        self.findings.append(f"Inferred Application Type: {app_type}")

    def generate_report(self) -> str:
        """Genera un reporte en formato Markdown."""
        report = []
        report.append(f"# Analysis Report for {self.url}")
        report.append("\n## Executive Summary")
        report.append(f"**Application Type:** {self.app_type_inference}")
        
        report.append("\n## Key Findings")
        for finding in self.findings:
            report.append(f"- {finding}")
            
        report.append("\n## Detailed Headers Analysis")
        for k, v in self.headers_analysis.items():
            report.append(f"- **{k}:** {v}")
            
        report.append("\n## Detailed HTML Analysis")
        for k, v in self.html_analysis.items():
            report.append(f"- **{k}:** {v}")
            
        return "\n".join(report)
