document.addEventListener('DOMContentLoaded', function () {
    const queryInput = document.getElementById('query-input');
    const chatContainer = document.getElementById('chat-container');
    const thinkingProcess = document.getElementById('thinking-process');
    const sendButton = document.getElementById('send-button');
    const signInBanner = document.getElementById('sign-in-banner');
    const updatedTermsBanner = document.getElementById('updated-terms-banner');
    const closeBannerBtn = document.getElementById('close-banner');
    const updatedTermsBannerCloseBtn = document.getElementById('updated-terms-banner-close');
    const userProfileImg = document.getElementById('user-profile-img');
    const inputAreaContainer = document.querySelector('.input-area-container');
    const welcomeModal = document.getElementById('welcome-modal');
    const closeWelcomeModalBtn = document.querySelector('.close-welcome-modal');
    const welcomeStartButton = document.getElementById('welcome-start-button');
    const exampleQuestions = document.querySelectorAll('.example-question');
    const whatsNewModal = document.getElementById('whats-new-modal');
    const closeWhatsNewModalBtn = document.querySelector('.close-whats-new-modal');
    const whatsNewGotItButton = document.getElementById('whats-new-got-it-button');

    let activeDetailsToggle = null;
    let highlightEnabled = false;
    let sendButtonEnabled = false;
    let isUserAuthenticated = false;
    let userTempUnit = null;
    let initialWindowHeight = window.innerHeight;
    let visualViewportSupported = 'visualViewport' in window;
    let isAndroid = /Android/i.test(navigator.userAgent);

    const bannerDismissed = localStorage.getItem('neubot_banner_dismissed') === 'true';
    const welcomeModalSeen = localStorage.getItem('neubot_welcome_seen') === 'true';
    const whatsNewModalSeen = localStorage.getItem('neubot_whats_new_20260630_seen') === 'true';
    const updatedTerms20260630Dismissed = localStorage.getItem('neubot_updated_terms_20260630_dismissed') === 'true';

    if (!welcomeModalSeen) {
        welcomeModal.style.display = 'block';
        setTimeout(() => {
            welcomeModal.classList.add('open');
        }, 10);
    }
    else if (welcomeModalSeen && !whatsNewModalSeen) {
        whatsNewModal.style.display = 'block';
        setTimeout(() => {
            whatsNewModal.classList.add('open');
        }, 10);
    }

    if (closeWelcomeModalBtn) {
        closeWelcomeModalBtn.addEventListener('click', () => {
            welcomeModal.classList.remove('open');
            setTimeout(() => {
                welcomeModal.style.display = 'none';
            }, 300);
            localStorage.setItem('neubot_welcome_seen', 'true');
        });
    }

    if (!updatedTerms20260630Dismissed) {
        updatedTermsBanner.style.display = 'flex';
    }

    if (closeWhatsNewModalBtn) {
        closeWhatsNewModalBtn.addEventListener('click', () => {
            whatsNewModal.classList.remove('open');
            setTimeout(() => {
                whatsNewModal.style.display = 'none';
            }, 300);
            localStorage.setItem('neubot_whats_new_20260630_seen', 'true');
        });
    }

    if (whatsNewGotItButton) {
        whatsNewGotItButton.addEventListener('click', () => {
            whatsNewModal.classList.remove('open');
            setTimeout(() => {
                whatsNewModal.style.display = 'none';
            }, 300);
            localStorage.setItem('neubot_whats_new_20260630_seen', 'true');

            setTimeout(() => {
                queryInput.focus();
            }, 400);
        });
    }

    whatsNewModal.addEventListener('click', (e) => {
        if (e.target === whatsNewModal) {
            whatsNewModal.classList.remove('open');
            setTimeout(() => {
                whatsNewModal.style.display = 'none';
            }, 300);
            localStorage.setItem('neubot_whats_new_20260630_seen', 'true');
        }
    });

    if (welcomeStartButton) {
        welcomeStartButton.addEventListener('click', () => {
            welcomeModal.classList.remove('open');
            setTimeout(() => {
                welcomeModal.style.display = 'none';
            }, 300);
            localStorage.setItem('neubot_welcome_seen', 'true');

            setTimeout(() => {
                queryInput.focus();
            }, 400);
        });
    }

    exampleQuestions.forEach(question => {
        question.addEventListener('click', () => {
            const questionText = question.getAttribute('data-question');

            queryInput.value = questionText;

            if (welcomeModal.style.display === 'block') {
                welcomeModal.classList.remove('open');
                setTimeout(() => {
                    welcomeModal.style.display = 'none';
                }, 300);
                localStorage.setItem('neubot_welcome_seen', 'true');
            } else if (whatsNewModal.style.display === 'block') {
                whatsNewModal.classList.remove('open');
                setTimeout(() => {
                    whatsNewModal.style.display = 'none';
                }, 300);
                localStorage.setItem('neubot_whats_new_20260630_seen', 'true');
            }

            setTimeout(() => {
                queryInput.focus();
                if (sendButtonEnabled) {
                    sendButton.classList.add('visible');
                }
            }, 400);
        });
    });

    welcomeModal.addEventListener('click', (e) => {
        if (e.target === welcomeModal) {
            welcomeModal.classList.remove('open');
            setTimeout(() => {
                welcomeModal.style.display = 'none';
            }, 300);
            localStorage.setItem('neubot_welcome_seen', 'true');
        }
    });

    // Clean up any leftover class on load
    document.body.classList.remove('keyboard-open');

    // Remove listeners if they exist (defensive)
    if (window.visualViewport) {
        try { window.visualViewport.removeEventListener('resize', detectVirtualKeyboard); } catch (e) { }
        try { window.visualViewport.removeEventListener('scroll', detectVirtualKeyboard); } catch (e) { }
    }

    // Strip focus/blur handlers affecting keyboard-open
    queryInput.onfocus = null;
    queryInput.onblur = null;

    function loadSettings() {
        const savedHighlight = localStorage.getItem('neubot_highlight_enabled');
        highlightEnabled = savedHighlight === 'true';

        const savedSendButton = localStorage.getItem('neubot_send_button_enabled');
        sendButtonEnabled = savedSendButton === 'true';

        const savedTemp = localStorage.getItem('neubot_temp_unit');
        if (savedTemp) {
            userTempUnit = savedTemp;
        } else {
            const lang = navigator.language || 'en-US';
            userTempUnit = (lang === 'en-US') ? 'f' : 'c';
        }

        const highlightToggle = document.getElementById('highlight-toggle');
        if (highlightToggle) {
            highlightToggle.checked = highlightEnabled;
        }

        const sendButtonToggle = document.getElementById('send-button-toggle');
        if (sendButtonToggle) {
            sendButtonToggle.checked = sendButtonEnabled;
        }

        const tempToggle = document.getElementById('temp-unit-toggle');
        if (tempToggle) {
            tempToggle.checked = (userTempUnit === 'f');
        }

        updateSendButtonVisibility();
    }

    function updateSendButtonVisibility() {
        if (sendButtonEnabled) {
            sendButton.classList.add('visible');
        } else {
            sendButton.classList.remove('visible');
        }
    }

    queryInput.addEventListener('input', function () {
        if (this.value.trim() !== '' && sendButtonEnabled) {
            sendButton.classList.add('visible');
        } else {
            sendButton.classList.remove('visible');
        }
    });

    queryInput.addEventListener('keypress', function (event) {
        if (event.key === 'Enter') {
            processQuery();
        }
    });

    sendButton.addEventListener('click', function () {
        this.classList.add('clicked');

        setTimeout(() => {
            this.classList.remove('clicked');
        }, 300);

        processQuery();
    });

    function processQuery() {
        const query = queryInput.value.trim();
        if (!query) return;


        queryInput.value = '';

        const userMessageDiv = addUserMessage(query, null);

        userMessageDiv.classList.add('sending');

        const typingIndicator = addTypingIndicator();

        fetch('/api/query', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                query: query,
                timezone: Intl.DateTimeFormat().resolvedOptions().timeZone
            }),
        })
            .then(response => response.json())
            .then(data => {
                typingIndicator.remove();

                if (highlightEnabled && data.highlightedQuery) {
                    const queryDiv = userMessageDiv.querySelector('.highlighted-query');
                    if (queryDiv) {
                        queryDiv.innerHTML = data.highlightedQuery;
                    }
                }

                addBotMessage(data.response, data.thoughts, data.widgets);

                scrollToBottom();
            })
            .catch(error => {
                console.error('Error:', error);
                typingIndicator.remove();
                addBotMessage('Sorry, something went wrong.', []);
                scrollToBottom();
            });
    }

    function addUserMessage(text, highlightedQuery = null) {
        const messageDiv = document.createElement('div');
        messageDiv.className = 'message user';

        const userImgSrc = isUserAuthenticated && userProfileImg.src ? userProfileImg.src : "user-icon.svg";

        messageDiv.innerHTML = `
            <div class="avatar">
                <img src="${userImgSrc}" alt="User">
            </div>
            <div class="message-content">
                <div class="highlighted-query">${text}</div>
            </div>
        `;

        chatContainer.appendChild(messageDiv);
        scrollToBottom();

        return messageDiv;
    }

    function addBotMessage(text, thoughts, serverWidgets = []) {
        const messageDiv = document.createElement('div');
        messageDiv.className = 'message bot';

        const stepsCount = thoughts.length;
        const detailsId = 'details-' + Date.now();
        const toggleId = 'toggle-' + Date.now();

        const usesPersonalContext = thoughts.some(t => {
            const desc = (t.description || '').toLowerCase();
            return desc.includes('personal') || desc.includes('identity') || desc.includes('user_name') || desc.includes('user context');
        });

        const contextLabel = usesPersonalContext ? ' using your personal context' : '';

        const messageHTML = `
            <div class="bot-icon"><img src="neubot-icon.svg" alt="Bot"></div>
            <div class="message-content">
                <div class="message-info">
                    Completed ${stepsCount} steps${contextLabel}
                    <span class="see-details" id="${toggleId}">See details</span>
                </div>
            </div>
        `;

        messageDiv.innerHTML = messageHTML;

        const messageContent = messageDiv.querySelector('.message-content');

        if (text) {
            const textMessage = document.createElement('div');
            textMessage.className = 'message-text';
            textMessage.innerHTML = text; // Server response is trusted enough for now
            messageContent.appendChild(textMessage);
        }

        // Render widgets from serverWidgets array
        serverWidgets.forEach(w => {
            if (w.type === 'search_results') {
                const searchResultsDiv = document.createElement('div');
                searchResultsDiv.innerHTML = formatSearchResults(w.data);
                messageContent.appendChild(searchResultsDiv);
            } else {
                const el = renderWidget(w);
                if (el) messageContent.appendChild(el);
            }
        });

        const detailsElement = document.createElement('div');
        detailsElement.id = detailsId;
        detailsElement.className = 'thinking-process';
        detailsElement.style.display = 'none';
        messageContent.appendChild(detailsElement);

        chatContainer.appendChild(messageDiv);

        displayThoughtProcess(thoughts, detailsElement);

        const toggleElement = document.getElementById(toggleId);
        if (toggleElement) {
            toggleElement.addEventListener('click', function () {
                if (detailsElement.style.display === 'none') {
                    if (activeDetailsToggle && activeDetailsToggle !== toggleElement) {
                        const activeDetailsId = activeDetailsToggle.getAttribute('data-details-id');
                        if (activeDetailsId) {
                            const activeDetails = document.getElementById(activeDetailsId);
                            if (activeDetails) activeDetails.style.display = 'none';
                            activeDetailsToggle.textContent = 'See details';
                        }
                    }

                    detailsElement.style.display = 'block';
                    toggleElement.textContent = 'Hide details';
                    toggleElement.setAttribute('data-details-id', detailsId);
                    activeDetailsToggle = toggleElement;
                } else {
                    detailsElement.style.display = 'none';
                    toggleElement.textContent = 'See details';
                    activeDetailsToggle = null;
                }
            });
        }

        scrollToBottom();
    }

    async function getRateLimits() {
        try {
            const response = await fetch('/api/limits');
            const limits = await response.json();
            return limits;
        } catch (error) {
            console.error('Error fetching rate limits:', error);
            return null;
        }
    }

    async function getUserInfo() {
        try {
            const response = await fetch('/api/user');
            const userInfo = await response.json();
            return userInfo;
        } catch (error) {
            console.error('Error fetching user info:', error);
            return { authenticated: false };
        }
    }

    function formatSearchResults(data) {
        if (data.error) {
            return `<div class="search-error">
                <div class="error-title">Error</div>
                <div class="error-message">${data.error}</div>
            </div>`;
        }

        let html = '<div class="search-results">';

        html += `<div class="search-header">${data.meta.header}</div>`;

        if (data.spellcheck) {
            html += `<div class="search-spellcheck">Did you mean: <em>${data.spellcheck}</em>?</div>`;
        }

        html += '<div class="search-results-container">';

        data.results.forEach(result => {
            html += `
                <div class="search-result">
                    <div class="search-result-header">
                        ${result.favicon ? `<img src="${result.favicon}" class="search-favicon" alt="">` : ''}
                        <a href="${result.url}" target="_blank" class="search-title">${result.title}</a>
                    </div>
                    <div class="search-url">${result.url}</div>
                    <div class="search-description">${result.description}</div>
                </div>
            `;
        });

        html += '</div></div>';
        return html;
    }

    function addTypingIndicator() {
        const indicatorDiv = document.createElement('div');
        indicatorDiv.className = 'message bot';

        indicatorDiv.innerHTML = `
            <div class="bot-icon"><img src="neubot-icon.svg" alt="Bot"></div>
            <div class="message-content">
                <div class="thinking-animation">
                    Processing<span class="thinking-dots">...</span>
                </div>
            </div>
        `;

        chatContainer.appendChild(indicatorDiv);

        const dots = indicatorDiv.querySelector('.thinking-dots');
        let dotCount = 0;
        const interval = setInterval(() => {
            dotCount = (dotCount % 3) + 1;
            dots.textContent = '.'.repeat(dotCount);
        }, 500);

        indicatorDiv.animationInterval = interval;

        indicatorDiv.remove = function () {
            clearInterval(this.animationInterval);
            this.parentNode.removeChild(this);
        };

        scrollToBottom();

        return indicatorDiv;
    }

    function displayThoughtProcess(thoughts, container) {
        container.innerHTML = '';

        thoughts.forEach((thought, index) => {
            const stepDiv = document.createElement('div');
            stepDiv.className = 'thought-step';

            const descriptionDiv = document.createElement('div');
            descriptionDiv.className = 'thought-description';
            descriptionDiv.textContent = thought.description;

            stepDiv.appendChild(descriptionDiv);

            if (thought.result && thought.result !== 'None') {
                const resultDiv = document.createElement('div');
                resultDiv.className = 'thought-result';
                resultDiv.textContent = thought.result;
                stepDiv.appendChild(resultDiv);
            }

            container.appendChild(stepDiv);
        });
    }

    function scrollToBottom() {
        chatContainer.scrollTop = chatContainer.scrollHeight;
    }

    addBotMessage('Hi! How can I help you?', []);

    // extractWidgets removed - no longer needed

    function renderWidget(widget) {
        // Backend now wraps content in 'data', logic below expects the content directly
        const content = widget.data || widget;

        switch (widget.type) {
            case 'home_assistant':
            case 'ha_result':
                return buildHaResultWidget(content);
            case 'fun_result':
                return buildFunResultWidget(content);
            case 'weather':
                return buildWeatherWidget(content);
            default:
                return null;
        }
    }

    function buildWeatherWidget(data) {
        const wrap = document.createElement('div');
        wrap.className = 'weather-block widget';

        // Basic weather display
        const tempC = Math.round(data.temperature.celsius);
        const tempF = Math.round(data.temperature.fahrenheit);

        let tempDisplay = '';
        if (userTempUnit === 'f') {
            tempDisplay = `<span class="weather-temp">${tempF}°F</span>`;
        } else {
            tempDisplay = `<span class="weather-temp">${tempC}°C</span>`;
        }

        wrap.innerHTML = `
            <div class="weather-header">
                <div class="weather-location">${data.location}</div>
                <div class="weather-condition">${data.condition}</div>
            </div>
            <div class="weather-main">
                ${tempDisplay}
            </div>
            <div class="weather-details">
                <span>Humidity: ${data.humidity}%</span>
            </div>
        `;
        return wrap;
    }

    function buildHaResultWidget(data) {
        const domain = data.domain || 'device';
        const devs = data.devices || [];
        const action = data.action || '';
        const applied = data.applied || {};

        const svgIconMap = {
            light: `<svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round" class="ha-svg-icon" style="display:inline-block; vertical-align:middle; margin-right:6px;"><circle cx="12" cy="12" r="5"></circle><line x1="12" y1="1" x2="12" y2="3"></line><line x1="12" y1="21" x2="12" y2="23"></line><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line><line x1="1" y1="12" x2="3" y2="12"></line><line x1="21" y1="12" x2="23" y2="12"></line><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line></svg>`,
            switch: `<svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round" class="ha-svg-icon" style="display:inline-block; vertical-align:middle; margin-right:6px;"><path d="M18.36 6.64a9 9 0 1 1-12.73 0"></path><line x1="12" y1="2" x2="12" y2="12"></line></svg>`,
            fan: `<svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round" class="ha-svg-icon" style="display:inline-block; vertical-align:middle; margin-right:6px;"><circle cx="12" cy="12" r="3"></circle><path d="M12 2v4a6 6 0 0 0 6 6h4"></path><path d="M12 22v-4a6 6 0 0 0-6-6H2"></path><path d="M22 12h-4a6 6 0 0 0-6 6v4"></path><path d="M2 12h4a6 6 0 0 0 6-6V2"></path></svg>`,
            scene: `<svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round" class="ha-svg-icon" style="display:inline-block; vertical-align:middle; margin-right:6px;"><polygon points="12 2 2 7 12 12 22 7 12 2"></polygon><polyline points="2 17 12 22 22 17"></polyline><polyline points="2 12 12 17 22 12"></polyline></svg>`,
            script: `<svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round" class="ha-svg-icon" style="display:inline-block; vertical-align:middle; margin-right:6px;"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>`,
            group: `<svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round" class="ha-svg-icon" style="display:inline-block; vertical-align:middle; margin-right:6px;"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"></path><polyline points="3.27 6.96 12 12.01 20.73 6.96"></polyline><line x1="12" y1="22.08" x2="12" y2="12"></line></svg>`,
            sensor: `<svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round" class="ha-svg-icon" style="display:inline-block; vertical-align:middle; margin-right:6px;"><path d="M14 14.76V3.5a2.5 2.5 0 0 0-5 0v11.26a4.5 4.5 0 1 0 5 0z"></path></svg>`,
            binary_sensor: `<svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round" class="ha-svg-icon" style="display:inline-block; vertical-align:middle; margin-right:6px;"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>`
        };

        const container = document.createElement('div');
        container.className = 'ha-device-cards-container';
        container.style.display = 'flex';
        container.style.flexWrap = 'wrap';
        container.style.gap = '12px';
        container.style.marginTop = '12px';
        container.style.width = '100%';

        devs.forEach(d => {
            const card = document.createElement('div');
            card.className = 'weather-block widget';
            card.style.margin = '0';
            card.style.padding = '12px 16px';
            card.style.minWidth = '220px';
            card.style.flex = '1 1 220px';
            card.style.position = 'relative';
            card.style.display = 'flex';
            card.style.flexDirection = 'column';
            card.style.justifyContent = 'space-between';

            // Find current state and individual device domain
            const devDomain = d.entity_id.split('.')[0];
            let stateVal = d.state_current || d.state_before || 'unknown';
            const reqAction = d.requested_action || action;
            if (reqAction === 'turn_on') {
                stateVal = d.success ? 'on' : (d.state_before || 'off');
            } else if (reqAction === 'turn_off') {
                stateVal = d.success ? 'off' : (d.state_before || 'on');
            }

            let cleanArea = d.name || d.entity_id;
            for (const suffix of [" Temperature", " temperature", " Temp", " temp", " Humidity", " humidity", " Presence", " presence", " Motion", " motion", " Occupancy", " occupancy", " Sensor", " sensor"]) {
                cleanArea = cleanArea.replace(suffix, "");
            }

            const thermometerSvg = `<svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round" class="ha-svg-icon" style="display:inline-block; vertical-align:middle; margin-right:6px;"><path d="M14 14.76V3.5a2.5 2.5 0 0 0-5 0v11.26a4.5 4.5 0 1 0 5 0z"></path></svg>`;
            const dropletSvg = `<svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round" class="ha-svg-icon" style="display:inline-block; vertical-align:middle; margin-right:6px;"><path d="M12 2.69l5.66 5.66a8 8 0 1 1-11.31 0z"></path></svg>`;
            const presenceSvg = `<svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round" class="ha-svg-icon" style="display:inline-block; vertical-align:middle; margin-right:6px;"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>`;

            let cardIcon = svgIconMap[devDomain] || `<svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round" class="ha-svg-icon" style="display:inline-block; vertical-align:middle; margin-right:6px;"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path><polyline points="9 22 9 12 15 12 15 22"></polyline></svg>`;
            let typeLabel = devDomain.charAt(0).toUpperCase() + devDomain.slice(1);

            let mainContentHtml = '';

            if (devDomain === 'sensor' || devDomain === 'binary_sensor') {
                const unit = (d.attributes && d.attributes.unit_of_measurement) || '';
                let valueDisplay = stateVal + unit;
                const stateLower = String(stateVal).toLowerCase();

                if (stateLower === 'unavailable' || stateLower === 'unknown') {
                    valueDisplay = `<span style="color:#ff5a67; font-weight:500; text-transform:capitalize;">${stateLower}</span>`;
                }

                if (devDomain === 'binary_sensor') {
                    typeLabel = 'Presence';
                    cardIcon = presenceSvg;
                    if (stateVal === 'on') {
                        valueDisplay = `<span style="color:#3ecf8e; font-weight:600;">Active</span>`;
                    } else if (stateVal === 'off') {
                        valueDisplay = `<span style="color:#889099; font-weight:600;">Clear</span>`;
                    }
                } else {
                    const devClass = d.attributes && d.attributes.device_class;
                    if (devClass === 'temperature' || d.entity_id.includes('temp') || unit.includes('°')) {
                        typeLabel = 'Temperature';
                        cardIcon = thermometerSvg;
                    } else if (devClass === 'humidity' || d.entity_id.includes('humid') || unit === '%') {
                        typeLabel = 'Humidity';
                        cardIcon = dropletSvg;
                    } else {
                        cardIcon = thermometerSvg;
                    }
                }

                mainContentHtml = `
                    <div class="weather-main" style="font-size:28px; font-weight:300; color:#fff; margin: 4px 0 0 0;">
                        ${valueDisplay}
                    </div>
                `;
            } else {
                const isOn = stateVal === 'on';
                const statusText = isOn ? 'On' : 'Off';
                const statusColor = isOn ? '#3ecf8e' : '#889099';

                const isChangingColor = !!(applied.color_name || devs.some(device => device.applied_color));

                let colorPickerHtml = '';
                if (devDomain === 'light' && isChangingColor) {
                    let currentColor = '#ffffff';
                    if (d.applied_color) {
                        if (d.applied_color.startsWith('#')) {
                            currentColor = d.applied_color;
                        } else {
                            const nameToHex = {
                                red: '#ff0000', green: '#00ff00', blue: '#0000ff',
                                yellow: '#ffff00', purple: '#800080', orange: '#ffa500',
                                pink: '#ffc0cb', white: '#ffffff', cyan: '#00ffff',
                                magenta: '#ff00ff'
                            };
                            currentColor = nameToHex[d.applied_color.toLowerCase()] || '#ffffff';
                        }
                    } else if (d.attributes && d.attributes.rgb_color) {
                        try {
                            const rgb = d.attributes.rgb_color;
                            currentColor = '#' + rgb.map(x => {
                                const hex = parseInt(x).toString(16);
                                return hex.length === 1 ? '0' + hex : hex;
                            }).join('');
                        } catch (e) { }
                    }

                    colorPickerHtml = `
                        <div class="ha-color-selector" style="display: flex; align-items: center; margin-top: 10px;">
                            <span style="font-size: 13px; color: #889099; margin-right: 8px;">Color:</span>
                            <div class="color-picker-trigger" style="width: 20px; height: 20px; border-radius: 50%; border: 2px solid #fff; background-color: ${currentColor}; cursor: pointer; position: relative; box-shadow: 0 0 4px rgba(0,0,0,0.5);" title="Pick Color">
                                <input type="color" class="ha-color-input" value="${currentColor}" data-entity-id="${d.entity_id}" style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; opacity: 0; cursor: pointer;">
                            </div>
                        </div>
                    `;
                }

                const toggleHtml = isChangingColor ? '' : `
                    <label class="toggle-switch">
                        <input type="checkbox" class="ha-device-toggle" data-entity-id="${d.entity_id}" ${isOn ? 'checked' : ''}>
                        <span class="toggle-slider"></span>
                    </label>
                `;

                mainContentHtml = `
                    <div style="display: flex; flex-direction: column; width: 100%;">
                        <div style="display: flex; align-items: center; justify-content: space-between; margin-top: 6px; width: 100%;">
                            <span class="ha-device-status-text" style="font-size: 20px; font-weight: 500; color: ${statusColor};">${statusText}</span>
                            ${toggleHtml}
                        </div>
                        ${colorPickerHtml}
                    </div>
                `;
            }

            card.innerHTML = `
                <div class="weather-header" style="border-bottom: 1px solid rgba(255,255,255,0.08); padding-bottom: 6px; margin-bottom: 8px; width: 100%;">
                    <div class="weather-location" style="display:flex; align-items:center; font-size:15px; font-weight:600; color:#fff; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
                        ${cardIcon} ${cleanArea}
                    </div>
                    <div class="weather-condition" style="font-size:12px; color:#889099; text-transform: capitalize;">
                        ${typeLabel}
                    </div>
                </div>
                ${mainContentHtml}
            `;

            // Attach event listeners
            const toggleInput = card.querySelector('.ha-device-toggle');
            if (toggleInput) {
                toggleInput.addEventListener('change', async function () {
                    const checked = this.checked;
                    const entityId = this.dataset.entityId;
                    const act = checked ? 'turn_on' : 'turn_off';
                    const statusTextEl = card.querySelector('.ha-device-status-text');
                    const switchContainer = this.closest('.toggle-switch');

                    if (statusTextEl) {
                        statusTextEl.textContent = checked ? 'On' : 'Off';
                        statusTextEl.style.color = checked ? '#3ecf8e' : '#889099';
                    }

                    if (switchContainer) {
                        switchContainer.classList.add('pending');
                        switchContainer.classList.remove('failed');
                    }
                    this.disabled = true;

                    try {
                        const res = await fetch('/api/integrations/home-assistant/control', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ entity_id: entityId, action: act })
                        });
                        const resData = await res.json();
                        if (switchContainer) {
                            switchContainer.classList.remove('pending');
                        }

                        if (resData.success) {
                            this.disabled = false;
                        } else {
                            console.error("Control failed:", resData.error);
                            if (switchContainer) {
                                switchContainer.classList.add('failed');
                            }
                            this.checked = !checked;
                            if (statusTextEl) {
                                statusTextEl.textContent = !checked ? 'On' : 'Off';
                                statusTextEl.style.color = !checked ? '#3ecf8e' : '#889099';
                            }
                            setTimeout(() => {
                                if (switchContainer) {
                                    switchContainer.classList.remove('failed');
                                }
                                this.disabled = false;
                            }, 1000);
                        }
                    } catch (e) {
                        console.error(e);
                        if (switchContainer) {
                            switchContainer.classList.remove('pending');
                            switchContainer.classList.add('failed');
                        }
                        this.checked = !checked;
                        if (statusTextEl) {
                            statusTextEl.textContent = !checked ? 'On' : 'Off';
                            statusTextEl.style.color = !checked ? '#3ecf8e' : '#889099';
                        }
                        setTimeout(() => {
                            if (switchContainer) {
                                switchContainer.classList.remove('failed');
                            }
                            this.disabled = false;
                        }, 1000);
                    }
                });
            }

            const colorInput = card.querySelector('.ha-color-input');
            if (colorInput) {
                colorInput.addEventListener('change', async function () {
                    const newColor = this.value;
                    const entityId = this.dataset.entityId;
                    const triggerEl = this.parentElement;

                    if (triggerEl) {
                        triggerEl.style.backgroundColor = newColor;
                    }

                    try {
                        const res = await fetch('/api/integrations/home-assistant/control', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ entity_id: entityId, action: 'turn_on', color: newColor })
                        });
                        const resData = await res.json();
                        if (!resData.success) {
                            console.error("Color control failed:", resData.error);
                        }
                    } catch (e) {
                        console.error(e);
                    }
                });
            }

            container.appendChild(card);
        });

        return container;
    }

    function buildFunResultWidget(data) {
        const wrap = document.createElement('div');
        wrap.className = 'fun-block widget';
        if (data.variant === 'self_destruct') {
            wrap.innerHTML = `<div class="fun-self-destruct"><div class="fun-title">Self Destruct Sequence</div><div class="countdown" aria-live="polite"></div><div class="final" style="display:none"></div></div>`;
            const cd = wrap.querySelector('.countdown');
            const finalEl = wrap.querySelector('.final');
            let remaining = data.countdown || 5;
            cd.textContent = remaining + 's';
            const interval = setInterval(() => {
                remaining -= 1;
                if (remaining <= 0) {
                    clearInterval(interval);
                    cd.style.display = 'none';
                    finalEl.style.display = 'block';
                    finalEl.textContent = data.finalText || '💥';
                } else {
                    cd.textContent = remaining + 's';
                }
            }, 1000);
        } else if (data.variant === 'rainbow') {
            wrap.innerHTML = `<div class="fun-rainbow"><div class="fun-title">Rainbow Lights</div><div class="sequence"></div><div class="done">${data.text || 'Done!'}</div></div>`;
            const seq = wrap.querySelector('.sequence');
            const colors = data.sequence || [];
            colors.forEach((c, i) => {
                const span = document.createElement('span');
                span.className = 'fun-color';
                span.style.background = c; span.title = c;
                span.style.setProperty('--delay', i * 0.15 + 's');
                seq.appendChild(span);
            });
        } else {
            wrap.textContent = data.text || 'Fun result';
        }
        return wrap;
    }

    const settingsModal = document.getElementById('settings-modal');
    const closeModalBtn = document.querySelector('.close-modal');
    const sidebarItems = document.querySelectorAll('.sidebar-item');
    const settingsBtn = document.getElementById('settings-button');

    settingsBtn.addEventListener('click', () => {
        settingsModal.style.display = 'block';
        setTimeout(() => {
            settingsModal.classList.add('open');

            sidebarItems.forEach(i => i.classList.remove('active'));
            document.querySelector('.sidebar-item[data-panel="account"]').classList.add('active');

            document.querySelectorAll('.panel').forEach(p => {
                p.classList.remove('active');
            });
            document.getElementById('account-panel').classList.add('active');

        }, 10);
        updateRateLimits();
        updateUserInfo();
    });

    // Deep link: open settings if URL hash is #settings
    if (window.location.hash === '#settings') {
        settingsBtn.click();
        // Clear the hash so it doesn't reopen on reload/back
        history.replaceState('', document.title, window.location.pathname + window.location.search);
    }

    closeModalBtn.addEventListener('click', () => {
        settingsModal.classList.remove('open');
        setTimeout(() => {
            settingsModal.style.display = 'none';
        }, 300);
    });

    settingsModal.addEventListener('click', (e) => {
        if (e.target === settingsModal) {
            settingsModal.classList.remove('open');
            setTimeout(() => {
                settingsModal.style.display = 'none';
            }, 300);
        }
    });


    sidebarItems.forEach(item => {
        item.addEventListener('click', () => {
            sidebarItems.forEach(i => i.classList.remove('active'));
            item.classList.add('active');

            document.querySelectorAll('.panel').forEach(p => {
                p.classList.remove('active');
            });

            const panelId = item.dataset.panel + '-panel';
            setTimeout(() => {
                document.getElementById(panelId).classList.add('active');
            }, 50);
        });
    });

    async function updateRateLimits() {
        try {
            const limits = await getRateLimits();

            const searchUsed = limits.search.used;
            const searchLimit = limits.search.limit;
            const searchRemaining = limits.search.remaining;

            document.getElementById('search-used').textContent = searchUsed;
            document.getElementById('search-limit').textContent = searchLimit;
            document.getElementById('search-remaining').textContent = searchRemaining;
            document.getElementById('search-progress').style.width =
                `${(searchUsed / searchLimit) * 100}%`;

            const weatherUsed = limits.weather.used;
            const weatherLimit = limits.weather.limit;
            const weatherRemaining = limits.weather.remaining;

            document.getElementById('weather-used').textContent = weatherUsed;
            document.getElementById('weather-limit').textContent = weatherLimit;
            document.getElementById('weather-remaining').textContent = weatherRemaining;
            document.getElementById('weather-progress').style.width =
                `${(weatherUsed / weatherLimit) * 100}%`;

            document.getElementById('days-remaining').textContent = limits.reset.days_remaining;

        } catch (error) {
            console.error('Error updating rate limits:', error);
        }
    }

    async function updateUserInfo() {
        try {
            const userInfo = await getUserInfo();
            const accountLoggedIn = document.getElementById('account-logged-in');
            const accountLoggedOut = document.getElementById('account-logged-out');
            const sidebarAvatarImg = document.getElementById('sidebar-avatar-img');
            const sidebarAccountName = document.getElementById('sidebar-account-name');
            const sidebarAccountEmail = document.getElementById('sidebar-account-email');

            isUserAuthenticated = userInfo.authenticated;

            if (isUserAuthenticated && userInfo.user && userInfo.user.temp_unit) {
                userTempUnit = userInfo.user.temp_unit;
            } else {
                const stored = localStorage.getItem('neubot_temp_unit');
                if (stored) {
                    userTempUnit = stored;
                } else {
                    const lang = navigator.language || 'en-US';
                    userTempUnit = (lang === 'en-US') ? 'f' : 'c';
                }
            }

            const tempToggle = document.getElementById('temp-unit-toggle');
            if (tempToggle) {
                tempToggle.checked = (userTempUnit === 'f');
            }

            if (userProfileImg) {
                if (isUserAuthenticated && userInfo.user.profile_pic) {
                    userProfileImg.src = userInfo.user.profile_pic;
                    userProfileImg.alt = userInfo.user.name || "User";
                } else {
                    userProfileImg.src = "user-icon.svg";
                    userProfileImg.alt = "User";
                }
            }

            if (signInBanner) {
                if (!isUserAuthenticated && !bannerDismissed) {
                    signInBanner.style.display = 'flex';
                } else {
                    signInBanner.style.display = 'none';
                }
            }

            if (sidebarAvatarImg && sidebarAccountName && sidebarAccountEmail) {
                if (isUserAuthenticated && userInfo.user) {
                    sidebarAvatarImg.src = userInfo.user.profile_pic || "user-icon.svg";
                    sidebarAccountName.textContent = userInfo.user.name || "User";
                    sidebarAccountEmail.textContent = userInfo.user.email || "";
                } else {
                    sidebarAvatarImg.src = "user-icon.svg";
                    sidebarAccountName.textContent = "Account";
                    sidebarAccountEmail.textContent = "Sign in for increased limits";
                }
            }

            if (userInfo.authenticated) {
                accountLoggedIn.style.display = 'block';
                accountLoggedOut.style.display = 'none';

                const userName = document.getElementById('user-name');
                const userEmail = document.getElementById('user-email');
                const userProvider = document.getElementById('user-provider');
                const userAvatar = document.getElementById('user-avatar');

                userName.textContent = userInfo.user.name;
                userEmail.textContent = userInfo.user.email;
                let providerName = userInfo.user.provider || '';
                if (providerName.toLowerCase() === 'joshatticusid') {
                    providerName = 'JoshAtticusID';
                } else if (providerName) {
                    providerName = providerName.charAt(0).toUpperCase() + providerName.slice(1);
                }
                userProvider.textContent = `Signed in with ${providerName}`;

                if (userInfo.user.profile_pic) {
                    userAvatar.src = userInfo.user.profile_pic;
                } else {
                    userAvatar.src = "user-icon.svg";
                }
            } else {
                accountLoggedIn.style.display = 'none';
                accountLoggedOut.style.display = 'block';
            }
        } catch (error) {
            console.error('Error updating user info:', error);
        }
    }

    setInterval(() => {
        if (settingsModal.classList.contains('open')) {
            updateRateLimits();
            updateUserInfo();
        }
    }, 60000);

    const highlightToggle = document.getElementById('highlight-toggle');
    highlightToggle.addEventListener('change', function () {
        highlightEnabled = this.checked;
        localStorage.setItem('neubot_highlight_enabled', highlightEnabled);
    });

    const sendButtonToggle = document.getElementById('send-button-toggle');
    sendButtonToggle.addEventListener('change', function () {
        sendButtonEnabled = this.checked;
        localStorage.setItem('neubot_send_button_enabled', sendButtonEnabled);
        updateSendButtonVisibility();
    });

    if (closeBannerBtn) {
        closeBannerBtn.addEventListener('click', function () {
            signInBanner.style.display = 'none';
            localStorage.setItem('neubot_banner_dismissed', 'true');
        });
    }

    if (updatedTermsBannerCloseBtn) {
        updatedTermsBannerCloseBtn.addEventListener('click', function () {
            updatedTermsBanner.style.display = 'none';
            localStorage.setItem('neubot_updated_terms_20260630_dismissed', 'true');
        });
    }

    loadSettings();

    updateUserInfo();
    updateRateLimits();

    const tempUnitToggle = document.getElementById('temp-unit-toggle');
    if (tempUnitToggle) {
        tempUnitToggle.addEventListener('change', async function () {
            const unit = this.checked ? 'f' : 'c';
            userTempUnit = unit;

            // Save locally immediately for visual consistency
            localStorage.setItem('neubot_temp_unit', unit);

            // If authenticated, sync with server
            if (isUserAuthenticated) {
                try {
                    await fetch('/api/show-settings', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ temp_unit: unit })
                    });
                } catch (e) { console.error('Error saving temp unit', e); }
            }
        });
    }
});
