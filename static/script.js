document.addEventListener('DOMContentLoaded', function() {
    const queryInput = document.getElementById('query-input');
    const chatContainer = document.getElementById('chat-container');
    const thinkingProcess = document.getElementById('thinking-process');
    const sendButton = document.getElementById('send-button');
    
    // Keep track of active details toggle
    let activeDetailsToggle = null;
    
    // Initialize settings
    let highlightEnabled = false;
    let sendButtonEnabled = false;
    
    // Load saved settings from localStorage
    function loadSettings() {
        const savedHighlight = localStorage.getItem('neubot_highlight_enabled');
        highlightEnabled = savedHighlight === 'true';
        
        const savedSendButton = localStorage.getItem('neubot_send_button_enabled');
        sendButtonEnabled = savedSendButton === 'true';
        
        // Update the toggles in the settings panel
        const highlightToggle = document.getElementById('highlight-toggle');
        if (highlightToggle) {
            highlightToggle.checked = highlightEnabled;
        }
        
        const sendButtonToggle = document.getElementById('send-button-toggle');
        if (sendButtonToggle) {
            sendButtonToggle.checked = sendButtonEnabled;
        }
        
        // Apply send button visibility
        updateSendButtonVisibility();
    }
    
    // Update send button visibility based on settings
    function updateSendButtonVisibility() {
        if (sendButtonEnabled) {
            sendButton.classList.add('visible');
        } else {
            sendButton.classList.remove('visible');
        }
    }
    
    // Handle input changes for send button visibility
    queryInput.addEventListener('input', function() {
        if (this.value.trim() !== '' && sendButtonEnabled) {
            sendButton.classList.add('visible');
        } else {
            sendButton.classList.remove('visible');
        }
    });
    
    // Handle Enter key press in input field
    queryInput.addEventListener('keypress', function(event) {
        if (event.key === 'Enter') {
            processQuery();
        }
    });
    
    // Handle send button click with animation
    sendButton.addEventListener('click', function() {
        this.classList.add('clicked');
        
        // Remove the class after animation completes
        setTimeout(() => {
            this.classList.remove('clicked');
        }, 300);
        
        processQuery();
    });
    
    function processQuery() {
        const query = queryInput.value.trim();
        if (!query) return;
        
        // Clear input
        queryInput.value = '';
        
        // Add user message first with plain text
        const userMessageDiv = addUserMessage(query, null);
        
        // Add sending animation class
        userMessageDiv.classList.add('sending');
        
        // Then add typing indicator
        const typingIndicator = addTypingIndicator();
        
        // Send request to API
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
            // Remove typing indicator
            typingIndicator.remove();
            
            // Update the specific user message with highlighted version if highlighting is enabled
            if (highlightEnabled && data.highlightedQuery) {
                const queryDiv = userMessageDiv.querySelector('.highlighted-query');
                if (queryDiv) {
                    queryDiv.innerHTML = data.highlightedQuery;
                }
            }
            
            // Add bot response
            addBotMessage(data.response, data.thoughts);
            
            // Scroll to bottom
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
        
        messageDiv.innerHTML = `
            <div class="avatar">
                <img src="user-icon.svg" alt="User">
            </div>
            <div class="message-content">
                <div class="highlighted-query">${text}</div>
            </div>
        `;
        
        chatContainer.appendChild(messageDiv);
        scrollToBottom();
        
        return messageDiv; // Return the message div for later reference
    }
    
    function addBotMessage(text, thoughts) {
        const messageDiv = document.createElement('div');
        messageDiv.className = 'message bot';
        
        const stepsCount = thoughts.length;
        const detailsId = 'details-' + Date.now();
        const toggleId = 'toggle-' + Date.now();
        
        // Try to parse the response as JSON for search results
        let searchResults = null;
        try {
            const data = JSON.parse(text);
            if (data.type === 'search_results') {
                searchResults = data;
            }
        } catch (e) {
            // Not JSON, treat as regular text
        }
        
        let messageContent;
        if (searchResults) {
            messageContent = formatSearchResults(searchResults);
        } else {
            messageContent = `<div class="message-text">${text}</div>`;
        }
        
        messageDiv.innerHTML = `
            <div class="bot-icon"><img src="neubot-icon.svg" alt="Bot"></div>
            <div class="message-content">
                <div class="message-info">
                    Completed ${stepsCount} steps
                    <span class="see-details" id="${toggleId}">See details</span>
                </div>
                ${messageContent}
                <div id="${detailsId}" class="thinking-process" style="display: none;"></div>
            </div>
        `;
        
        chatContainer.appendChild(messageDiv);
        
        // Fill the thinking process content
        const detailsElement = document.getElementById(detailsId);
        displayThoughtProcess(thoughts, detailsElement);
        
        // Set up toggle behavior
        const toggleElement = document.getElementById(toggleId);
        toggleElement.addEventListener('click', function() {
            if (detailsElement.style.display === 'none') {
                // Hide any previously open details
                if (activeDetailsToggle && activeDetailsToggle !== toggleElement) {
                    const activeDetailsId = activeDetailsToggle.getAttribute('data-details-id');
                    if (activeDetailsId) {
                        const activeDetails = document.getElementById(activeDetailsId);
                        if (activeDetails) activeDetails.style.display = 'none';
                        activeDetailsToggle.textContent = 'See details';
                    }
                }
                
                // Show this details
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
    
    // Add this function to fetch rate limits
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

    // Update the search results formatting to handle rate limit errors
    function formatSearchResults(data) {
        if (data.error) {
            return `<div class="search-error">
                <div class="error-title">Error</div>
                <div class="error-message">${data.error}</div>
            </div>`;
        }
    
        let html = '<div class="search-results">';
        
        // Add header
        html += `<div class="search-header">${data.meta.header}</div>`;
        
        // Add spell check suggestion if present
        if (data.spellcheck) {
            html += `<div class="search-spellcheck">Did you mean: <em>${data.spellcheck}</em>?</div>`;
        }
        
        // Add results container
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
        
        // Animate dots
        const dots = indicatorDiv.querySelector('.thinking-dots');
        let dotCount = 0;
        const interval = setInterval(() => {
            dotCount = (dotCount % 3) + 1;
            dots.textContent = '.'.repeat(dotCount);
        }, 500);
        
        // Store the interval ID so we can clear it later
        indicatorDiv.animationInterval = interval;
        
        // Custom remove method that also clears the interval
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
    
    // Add a welcome message when the page loads
    addBotMessage('Hi! My name is neubot. How can I help you today?', []);

    // Add after existing DOMContentLoaded code
    const settingsModal = document.getElementById('settings-modal');
    const closeModalBtn = document.querySelector('.close-modal');
    const sidebarItems = document.querySelectorAll('.sidebar-item');

    // Add settings button to header
    const h1 = document.querySelector('h1');
    const settingsBtn = document.createElement('button');
    settingsBtn.className = 'settings-button';
    settingsBtn.innerHTML = '⚙️';
    h1.appendChild(settingsBtn);

    // Settings button styles
    const style = document.createElement('style');
    style.textContent = `
        .settings-button {
            background: none;
            border: none;
            color: #fff;
            font-size: 24px;
            cursor: pointer;
            padding: 5px;
            margin-left: 10px;
            transition: transform 0.3s;
        }
        .settings-button:hover {
            transform: rotate(90deg);
        }
    `;
    document.head.appendChild(style);

    // Modal functionality
    settingsBtn.addEventListener('click', () => {
        settingsModal.style.display = 'block';
        setTimeout(() => {
            settingsModal.classList.add('open');
        }, 10); // Small delay to ensure transition works
        updateRateLimits();
    });

    closeModalBtn.addEventListener('click', () => {
        settingsModal.classList.remove('open');
        setTimeout(() => {
            settingsModal.style.display = 'none';
        }, 300); // Match the transition duration
    });

    settingsModal.addEventListener('click', (e) => {
        if (e.target === settingsModal) {
            settingsModal.classList.remove('open');
            setTimeout(() => {
                settingsModal.style.display = 'none';
            }, 300);
        }
    });

    // Sidebar navigation with animation
    sidebarItems.forEach(item => {
        item.addEventListener('click', () => {
            // Remove active class from all items
            sidebarItems.forEach(i => i.classList.remove('active'));
            // Add active class to clicked item
            item.classList.add('active');
            
            // Hide all panels first
            document.querySelectorAll('.panel').forEach(p => {
                p.classList.remove('active');
            });
            
            // Show corresponding panel with a small delay for transition
            const panelId = item.dataset.panel + '-panel';
            setTimeout(() => {
                document.getElementById(panelId).classList.add('active');
            }, 50);
        });
    });

    // Rate limits functionality
    async function updateRateLimits() {
        try {
            const limits = await getRateLimits();
            
            // Update search limits
            const searchUsed = limits.search.used;
            const searchLimit = limits.search.limit;
            const searchRemaining = limits.search.remaining;
            
            document.getElementById('search-used').textContent = searchUsed;
            document.getElementById('search-limit').textContent = searchLimit;
            document.getElementById('search-remaining').textContent = searchRemaining;
            document.getElementById('search-progress').style.width = 
                `${(searchUsed / searchLimit) * 100}%`;
            
            // Update weather limits
            const weatherUsed = limits.weather.used;
            const weatherLimit = limits.weather.limit;
            const weatherRemaining = limits.weather.remaining;
            
            document.getElementById('weather-used').textContent = weatherUsed;
            document.getElementById('weather-limit').textContent = weatherLimit;
            document.getElementById('weather-remaining').textContent = weatherRemaining;
            document.getElementById('weather-progress').style.width = 
                `${(weatherUsed / weatherLimit) * 100}%`;
            
            // Update total limits
            const totalUsed = limits.total.used;
            const totalLimit = limits.total.limit;
            const totalRemaining = limits.total.remaining;
            
            document.getElementById('total-used').textContent = totalUsed;
            document.getElementById('total-limit').textContent = totalLimit;
            document.getElementById('total-remaining').textContent = totalRemaining;
            document.getElementById('total-progress').style.width = 
                `${(totalUsed / totalLimit) * 100}%`;
            
            // Update reset information
            document.getElementById('days-remaining').textContent = limits.reset.days_remaining;
            
        } catch (error) {
            console.error('Error updating rate limits:', error);
        }
    }

    // Update rate limits every 60 seconds if modal is open
    setInterval(() => {
        if (settingsModal.classList.contains('open')) {
            updateRateLimits();
        }
    }, 60000);

    // Add after existing modal code
    // Settings functionality
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
    
    // Load saved settings on page load
    loadSettings();
    
    // Make general panel active by default instead of rate-limits
    document.querySelectorAll('.sidebar-item').forEach(item => {
        item.classList.remove('active');
    });
    document.querySelector('.sidebar-item[data-panel="general"]').classList.add('active');
    
    document.querySelectorAll('.panel').forEach(panel => {
        panel.classList.remove('active');
    });
    document.getElementById('general-panel').classList.add('active');
});