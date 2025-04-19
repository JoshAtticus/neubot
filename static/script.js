document.addEventListener('DOMContentLoaded', function() {
    const queryInput = document.getElementById('query-input');
    const chatContainer = document.getElementById('chat-container');
    const thinkingProcess = document.getElementById('thinking-process');
    const sendButton = document.getElementById('send-button');
    const signInBanner = document.getElementById('sign-in-banner');
    const closeBannerBtn = document.getElementById('close-banner');
    const userProfileImg = document.getElementById('user-profile-img');
    const inputAreaContainer = document.querySelector('.input-area-container');
    const welcomeModal = document.getElementById('welcome-modal');
    const closeWelcomeModalBtn = document.querySelector('.close-welcome-modal');
    const welcomeStartButton = document.getElementById('welcome-start-button');
    const exampleQuestions = document.querySelectorAll('.example-question');
    
    let activeDetailsToggle = null;
    let highlightEnabled = false;
    let sendButtonEnabled = false;
    let isUserAuthenticated = false;
    let initialWindowHeight = window.innerHeight;
    let visualViewportSupported = 'visualViewport' in window;
    let isAndroid = /Android/i.test(navigator.userAgent);
    
    const bannerDismissed = localStorage.getItem('neubot_banner_dismissed') === 'true';
    const welcomeModalSeen = localStorage.getItem('neubot_welcome_seen') === 'true';
    
    if (!welcomeModalSeen) {
        welcomeModal.style.display = 'block';
        setTimeout(() => {
            welcomeModal.classList.add('open');
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
            
            welcomeModal.classList.remove('open');
            setTimeout(() => {
                welcomeModal.style.display = 'none';
            }, 300);
            localStorage.setItem('neubot_welcome_seen', 'true');
            
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
    
    function detectVirtualKeyboard() {
        if (window.innerWidth <= 1024) {
            if (visualViewportSupported) {
                const heightDifference = initialWindowHeight - window.visualViewport.height;
                const isKeyboardOpen = heightDifference > 150;
                
                if (isKeyboardOpen) {
                    document.body.classList.add('keyboard-open');
                    
                    if (isAndroid) {
                        const viewportBottom = window.visualViewport.offsetTop + window.visualViewport.height;
                        inputAreaContainer.style.bottom = `${window.innerHeight - viewportBottom}px`;
                    }
                    
                    setTimeout(scrollToBottom, 100);
                } else {
                    document.body.classList.remove('keyboard-open');
                    if (isAndroid) {
                        inputAreaContainer.style.bottom = '0';
                    }
                }
            } 
            else {
                const heightDifference = initialWindowHeight - window.innerHeight;
                const isKeyboardOpen = heightDifference > 150;
                
                if (isKeyboardOpen) {
                    document.body.classList.add('keyboard-open');
                    setTimeout(scrollToBottom, 100);
                } else {
                    document.body.classList.remove('keyboard-open');
                }
            }
        }
    }
    
    window.addEventListener('orientationchange', function() {
        setTimeout(() => {
            initialWindowHeight = window.innerHeight;
            if (visualViewportSupported && window.visualViewport) {
                initialWindowHeight = window.visualViewport.height;
            }
        }, 300);
    });

    if (visualViewportSupported) {
        window.visualViewport.addEventListener('resize', function() {
            detectVirtualKeyboard();
        });
        
        window.visualViewport.addEventListener('scroll', function() {
            if (isAndroid && document.body.classList.contains('keyboard-open')) {
                const viewportBottom = window.visualViewport.offsetTop + window.visualViewport.height;
                inputAreaContainer.style.bottom = `${window.innerHeight - viewportBottom}px`;
            }
        });
    } else {
        window.addEventListener('resize', function() {
            detectVirtualKeyboard();
        });
    }
    
    queryInput.addEventListener('focus', function() {
        if (window.innerWidth <= 1024) {
            document.body.classList.add('keyboard-open');
            setTimeout(() => {
                scrollToBottom();
                if (isAndroid) {
                    setTimeout(scrollToBottom, 500);
                }
            }, 300);
        }
    });
    
    queryInput.addEventListener('blur', function() {
        if (window.innerWidth <= 1024) {
            setTimeout(() => {
                document.body.classList.remove('keyboard-open');
                if (isAndroid) {
                    inputAreaContainer.style.bottom = '0';
                }
            }, 100);
        }
    });
    
    function loadSettings() {
        const savedHighlight = localStorage.getItem('neubot_highlight_enabled');
        highlightEnabled = savedHighlight === 'true';
        
        const savedSendButton = localStorage.getItem('neubot_send_button_enabled');
        sendButtonEnabled = savedSendButton === 'true';
        
        const highlightToggle = document.getElementById('highlight-toggle');
        if (highlightToggle) {
            highlightToggle.checked = highlightEnabled;
        }
        
        const sendButtonToggle = document.getElementById('send-button-toggle');
        if (sendButtonToggle) {
            sendButtonToggle.checked = sendButtonEnabled;
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
    
    queryInput.addEventListener('input', function() {
        if (this.value.trim() !== '' && sendButtonEnabled) {
            sendButton.classList.add('visible');
        } else {
            sendButton.classList.remove('visible');
        }
    });
    
    queryInput.addEventListener('keypress', function(event) {
        if (event.key === 'Enter') {
            processQuery();
        }
    });
    
    sendButton.addEventListener('click', function() {
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
            
            addBotMessage(data.response, data.thoughts);
            
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
    
    function addBotMessage(text, thoughts) {
        const messageDiv = document.createElement('div');
        messageDiv.className = 'message bot';
        
        const stepsCount = thoughts.length;
        const detailsId = 'details-' + Date.now();
        const toggleId = 'toggle-' + Date.now();
        
        let spotifyData = null;
        let searchResults = null;
        let plainText = text;
        
        try {
            const data = JSON.parse(text);
            if (data.type === 'search_results') {
                searchResults = data;
                plainText = null;
            } else if (data.type === 'spotify_track') {
                spotifyData = data;
                plainText = null;
            }
        } catch (e) {
            const jsonRegex = /\{"type":\s*"(spotify_track|search_results)".*?\}/gs;
            const match = text.match(jsonRegex);
            
            if (match) {
                try {
                    const jsonData = JSON.parse(match[0]);
                    
                    if (jsonData.type === 'spotify_track') {
                        spotifyData = jsonData;
                        plainText = text.replace(jsonRegex, '').trim();
                    } else if (jsonData.type === 'search_results') {
                        searchResults = jsonData;
                        plainText = text.replace(jsonRegex, '').trim();
                    }
                } catch (err) {
                    plainText = text;
                }
            } else {
                plainText = text;
            }
        }

        const messageHTML = `
            <div class="bot-icon"><img src="neubot-icon.svg" alt="Bot"></div>
            <div class="message-content">
                <div class="message-info">
                    Completed ${stepsCount} steps
                    <span class="see-details" id="${toggleId}">See details</span>
                </div>
            </div>
        `;
        
        messageDiv.innerHTML = messageHTML;
        
        const messageContent = messageDiv.querySelector('.message-content');
        
        if (plainText) {
            const textMessage = document.createElement('div');
            textMessage.className = 'message-text';
            textMessage.innerHTML = plainText;
            messageContent.appendChild(textMessage);
        }
        
        if (searchResults) {
            const searchResultsDiv = document.createElement('div');
            searchResultsDiv.innerHTML = formatSearchResults(searchResults);
            messageContent.appendChild(searchResultsDiv);
        }
        
        if (spotifyData) {
            const trackData = {
                trackName: spotifyData.track_name,
                artist: spotifyData.artist,
                albumArt: spotifyData.album_art,
                trackUrl: spotifyData.track_url
            };
            
            const playerElement = createSpotifyPlayerForChat(trackData);
            messageContent.appendChild(playerElement);
        }
        
        const detailsElement = document.createElement('div');
        detailsElement.id = detailsId;
        detailsElement.className = 'thinking-process';
        detailsElement.style.display = 'none';
        messageContent.appendChild(detailsElement);
        
        chatContainer.appendChild(messageDiv);
        
        displayThoughtProcess(thoughts, detailsElement);
        
        const toggleElement = document.getElementById(toggleId);
        toggleElement.addEventListener('click', function() {
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
        
        indicatorDiv.remove = function() {
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
            
            const totalUsed = limits.total.used;
            const totalLimit = limits.total.limit;
            const totalRemaining = limits.total.remaining;
            
            document.getElementById('total-used').textContent = totalUsed;
            document.getElementById('total-limit').textContent = totalLimit;
            document.getElementById('total-remaining').textContent = totalRemaining;
            document.getElementById('total-progress').style.width = 
                `${(totalUsed / totalLimit) * 100}%`;
            
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
                userProvider.textContent = `Signed in with ${userInfo.user.provider.charAt(0).toUpperCase() + userInfo.user.provider.slice(1)}`;
                
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
    highlightToggle.addEventListener('change', function() {
        highlightEnabled = this.checked;
        localStorage.setItem('neubot_highlight_enabled', highlightEnabled);
    });
    
    const sendButtonToggle = document.getElementById('send-button-toggle');
    sendButtonToggle.addEventListener('change', function() {
        sendButtonEnabled = this.checked;
        localStorage.setItem('neubot_send_button_enabled', sendButtonEnabled);
        updateSendButtonVisibility();
    });
    
    if (closeBannerBtn) {
        closeBannerBtn.addEventListener('click', function() {
            signInBanner.style.display = 'none';
            localStorage.setItem('neubot_banner_dismissed', 'true');
        });
    }
    
    loadSettings();
    
    updateUserInfo();
    updateRateLimits();
});

function createSpotifyPlayerForChat(trackData) {
    const playerContainer = document.createElement('div');
    playerContainer.className = 'spotify-player-chat';
    
    const albumArt = document.createElement('div');
    albumArt.className = 'spotify-album-art';
    
    const albumImg = document.createElement('img');
    albumImg.src = trackData.albumArt || 'https://via.placeholder.com/60?text=No+Image';
    albumImg.alt = 'Album Art';
    albumArt.appendChild(albumImg);
    
    const trackInfo = document.createElement('div');
    trackInfo.className = 'spotify-track-info';
    
    const trackName = document.createElement('div');
    trackName.className = 'spotify-track-name';
    trackName.textContent = trackData.trackName;
    trackInfo.appendChild(trackName);
    
    const artistName = document.createElement('div');
    artistName.className = 'spotify-track-artist';
    artistName.textContent = trackData.artist;
    trackInfo.appendChild(artistName);
    
    const attribution = document.createElement('div');
    attribution.className = 'spotify-attribution';
    
    const spotifyLink = document.createElement('a');
    spotifyLink.href = trackData.trackUrl || 'https://open.spotify.com/';
    spotifyLink.target = '_blank';
    spotifyLink.textContent = 'Powered by ';
    
    const spotifyLogo = document.createElement('img');
    spotifyLogo.src = 'https://storage.googleapis.com/pr-newsroom-wp/1/2018/11/Spotify_Logo_RGB_Green.png';
    spotifyLogo.alt = 'Spotify';
    
    spotifyLink.appendChild(spotifyLogo);
    attribution.appendChild(spotifyLink);
    trackInfo.appendChild(attribution);
    
    playerContainer.appendChild(albumArt);
    playerContainer.appendChild(trackInfo);
    
    return playerContainer;
}