export const syncAuthToLangfuse = (token: string) => {
  // Create an invisible iframe to securely plant the token into Langfuse's NextAuth
  const iframe = document.createElement('iframe');

  const host = (import.meta.env.VITE_LANGFUSE_HOST || `${window.location.protocol}//${window.location.hostname}:3000`).replace(/\/$/, '');
  
  // Hit the Langfuse credential endpoint
  iframe.src = `${host}/api/auth/signin?token=${token}`;
  iframe.style.display = 'none';
  
  document.body.appendChild(iframe);
  
  // Clean it up after 2 seconds
  setTimeout(() => {
    if (document.body.contains(iframe)) {
      document.body.removeChild(iframe);
    }
  }, 2000);
};