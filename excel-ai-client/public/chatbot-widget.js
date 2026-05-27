/**
 * Floating Chatbot Widget
 * Embed this script on any website to add a floating chatbot
 * 
 * Usage:
 * <script src="https://your-domain.com/chatbot-widget.js" data-collection-id="col_abc123"></script>
 */

(function() {
  'use strict';

  // Configuration
  const config = {
    collectionId: null,
    shareToken: null, // Workspace share token (alternative to collectionId)
    baseUrl: null, // Will be set from data-base-url or fallback to script origin
    widgetId: 'chatbot-widget-container',
    buttonId: 'chatbot-widget-button',
    iframeId: 'chatbot-widget-iframe',
    position: 'bottom-right', // bottom-right, bottom-left
    buttonSize: 60,
    widgetWidth: 400,
    widgetHeight: 600,
    zIndex: 9999
  };
  
  // Global state to track custom icon (accessible to API functions)
  const widgetState = {
    hasCustomIcon: false,
    customIconUrl: null
  };

  // Get collection ID from script tag
  const scriptTag = document.currentScript || document.querySelector('script[data-collection-id]');
  if (scriptTag && scriptTag.getAttribute('data-collection-id')) {
    config.collectionId = scriptTag.getAttribute('data-collection-id');
  }

  // Get custom base URL if provided
  if (scriptTag && scriptTag.getAttribute('data-base-url')) {
    config.baseUrl = scriptTag.getAttribute('data-base-url');
  } else {
    // Fallback: try to get from script src
    if (scriptTag && scriptTag.src) {
      try {
        const scriptUrl = new URL(scriptTag.src);
        config.baseUrl = scriptUrl.origin;
      } catch (e) {
        // If URL parsing fails, use window.location.origin as last resort
        config.baseUrl = window.location.origin;
      }
    } else {
      config.baseUrl = window.location.origin;
    }
  }

  // Get workspace share token if provided
  if (scriptTag && scriptTag.getAttribute('data-share-token')) {
    config.shareToken = scriptTag.getAttribute('data-share-token');
  }

  if (!config.collectionId && !config.shareToken) {
    console.error('Chatbot Widget: Either data-collection-id or data-share-token is required.');
    return;
  }

  // Create widget container
  function createWidget() {
    // Check if widget already exists
    if (document.getElementById(config.widgetId)) {
      return;
    }

    // Create container
    const container = document.createElement('div');
    container.id = config.widgetId;
    container.style.cssText = `
      position: fixed;
      ${config.position === 'bottom-right' ? 'right: 20px;' : 'left: 20px;'}
      bottom: 20px;
      z-index: ${config.zIndex};
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
    `;

    // Create iframe container (hidden by default)
    const iframeContainer = document.createElement('div');
    iframeContainer.id = 'chatbot-iframe-container';
    iframeContainer.style.cssText = `
      width: ${config.widgetWidth}px;
      height: ${config.widgetHeight}px;
      background: white;
      border-radius: 12px;
      box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15);
      display: none;
      overflow: hidden;
      margin-bottom: 10px;
      border: 1px solid #e5e7eb;
      position: relative;
    `;
    
    // Listen for close message from iframe
    window.addEventListener('message', function(event) {
      if (event.data && event.data.type === 'closeChatbot') {
        isOpen = false;
        iframeContainer.style.display = 'none';
        button.style.display = 'flex'; // Show floating button when chat is closed
        button.setAttribute('aria-label', 'Open Chatbot');
        // Preserve custom icon - don't override it
        if (widgetState.hasCustomIcon && widgetState.customIconUrl) {
          setCustomIcon(widgetState.customIconUrl);
        }
      }
    });

    // Create iframe
    const iframe = document.createElement('iframe');
    iframe.id = config.iframeId;
    // Use share token route for workspace chatbots, collection route for document chatbots
    if (config.shareToken) {
      iframe.src = `${config.baseUrl}/#/shared/workspace/${config.shareToken}/chat`;
    } else {
      iframe.src = `${config.baseUrl}/#/embed-chatbot/${config.collectionId}`;
    }
    iframe.style.cssText = `
      width: 100%;
      height: 100%;
      border: none;
      display: block;
    `;
    iframe.setAttribute('allow', 'microphone');
    iframe.setAttribute('allowfullscreen', 'false');

    iframeContainer.appendChild(iframe);
    container.appendChild(iframeContainer);

    // Create floating button - logo will be the button itself
    const button = document.createElement('button');
    button.id = config.buttonId;
    button.type = 'button';
    button.setAttribute('aria-label', 'Open Chatbot');
    
    // Use global state for custom icon tracking
    
    // Default button styles (used when no custom icon)
    const defaultButtonStyle = `
      width: ${config.buttonSize}px;
      height: ${config.buttonSize}px;
      border-radius: 50%;
      background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
      border: none;
      cursor: pointer;
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
      display: flex;
      align-items: center;
      justify-content: center;
      transition: transform 0.2s, box-shadow 0.2s;
      color: white;
      font-size: 24px;
      padding: 0;
      overflow: hidden;
    `;
    
    // Default icon - robot with speech bubble
    const defaultIcon = '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>';
    
    // Function to set default icon
    function setDefaultIcon() {
      widgetState.hasCustomIcon = false;
      widgetState.customIconUrl = null;
      button.style.cssText = defaultButtonStyle;
      button.innerHTML = defaultIcon;
    }
    
    // Function to set custom icon as button
    function setCustomIcon(iconUrl) {
      widgetState.hasCustomIcon = true;
      widgetState.customIconUrl = iconUrl;
      
      // Make the logo itself be the button
      button.style.cssText = `
        width: ${config.buttonSize}px;
        height: ${config.buttonSize}px;
        border-radius: 50%;
        background: transparent;
        border: 3px solid white;
        cursor: pointer;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
        display: flex;
        align-items: center;
        justify-content: center;
        transition: transform 0.2s, box-shadow 0.2s;
        padding: 0;
        overflow: hidden;
        background-image: url('${iconUrl}');
        background-size: cover;
        background-position: center;
        background-repeat: no-repeat;
      `;
      button.innerHTML = ''; // Remove default icon
      
      // Add error handling for the background image
      const img = new Image();
      img.onload = function() {
        // Image loaded successfully, keep the custom icon
        widgetState.hasCustomIcon = true;
      };
      img.onerror = function() {
        // If image fails to load, revert to default
        console.warn('Custom icon failed to load, using default');
        setDefaultIcon();
      };
      img.src = iconUrl;
    }
    
    // Initialize with default icon
    setDefaultIcon();
    
    // Try to load custom icon with retry logic
    function loadCustomIcon(retryCount = 0) {
      const maxRetries = 3;
      fetch(`${config.baseUrl}/api/collection/${config.collectionId}`)
        .then(response => {
          if (!response.ok) throw new Error('Failed to fetch collection');
          return response.json();
        })
        .then(data => {
          // Only use custom icon if it exists, otherwise keep default
          if (data.custom_icon_url && data.custom_icon_url.trim()) {
            const iconUrl = data.custom_icon_url.startsWith('http') 
              ? data.custom_icon_url 
              : `${config.baseUrl}${data.custom_icon_url}`;
            setCustomIcon(iconUrl);
          } else {
            // No custom icon, ensure default is shown
            setDefaultIcon();
          }
        })
        .catch(err => {
          console.log('Could not load custom icon:', err);
          if (retryCount < maxRetries) {
            // Retry after a delay
            setTimeout(() => loadCustomIcon(retryCount + 1), 1000 * (retryCount + 1));
          } else {
            // After max retries, ensure default icon is shown
            setDefaultIcon();
          }
        });
    }
    
    // Load custom icon (will set default if none exists)
    loadCustomIcon();

    // Button hover effect
    button.addEventListener('mouseenter', function() {
      this.style.transform = 'scale(1.1)';
      this.style.boxShadow = '0 6px 16px rgba(0, 0, 0, 0.2)';
    });
    button.addEventListener('mouseleave', function() {
      this.style.transform = 'scale(1)';
      this.style.boxShadow = '0 4px 12px rgba(0, 0, 0, 0.15)';
    });

    // Toggle widget - hide button when chat is open, show when closed
    let isOpen = false;
    button.addEventListener('click', function() {
      isOpen = !isOpen;
      if (isOpen) {
        iframeContainer.style.display = 'block';
        button.style.display = 'none'; // Hide floating button when chat is open
        button.setAttribute('aria-label', 'Chatbot is open');
      } else {
        iframeContainer.style.display = 'none';
        button.style.display = 'flex'; // Show floating button when chat is closed
        button.setAttribute('aria-label', 'Open Chatbot');
      }
      // Preserve custom icon state - don't change the button appearance
      if (widgetState.hasCustomIcon && widgetState.customIconUrl) {
        // Ensure custom icon is still set
        setCustomIcon(widgetState.customIconUrl);
      }
    });

    container.appendChild(button);
    document.body.appendChild(container);
  }

  // Initialize widget when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', createWidget);
  } else {
    createWidget();
  }

  // Expose API for programmatic control
  window.ChatbotWidget = {
    open: function() {
      const container = document.getElementById(config.widgetId);
      const iframeContainer = document.getElementById('chatbot-iframe-container');
      const button = document.getElementById(config.buttonId);
      if (container && iframeContainer && button) {
        iframeContainer.style.display = 'block';
        button.style.display = 'none'; // Hide floating button when chat is open
      }
    },
    close: function() {
      const container = document.getElementById(config.widgetId);
      const iframeContainer = document.getElementById('chatbot-iframe-container');
      const button = document.getElementById(config.buttonId);
      if (container && iframeContainer && button) {
        iframeContainer.style.display = 'none';
        button.style.display = 'flex'; // Show floating button when chat is closed
      }
    },
    toggle: function() {
      const button = document.getElementById(config.buttonId);
      if (button) {
        button.click();
      }
    }
  };
})();

