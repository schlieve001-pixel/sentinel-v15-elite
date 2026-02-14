#!/bin/bash
cd ~/origin/continuity_lab
cat > ~/google_credentials.json << 'EOF'
{
  "type": "service_account",
  "project_id": "canvas-sum-481614-f6",
  "private_key_id": "35050c0be70f33fb6c07eac575bf775ebde1d5be",
  "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQDz/rh7VYtZDLIc\nDnKN0EbOS8nzsZgKECJzow/r9WEcyb3QTG6mw6Fm6Y3XmmaMhc4YQJPTAxag2YnU\nFfWtBoLKSt4MmRqFW+vpMJkHJtBYnnYkYtYh/+VV/z/i2Nk3oCkq/ren7drh1A5F\nOS0koaOBvQ2oVm3ciFrtHJyazrKdlsQbOXdM54OaXawU95Le8sKcknHp3Yb69rwQ\nDF0k14U9AY3YbMHIRE4HSI5Y9Q6Xg/U9HQsUwg+UIUFFVsUOcD0Vt+fNU5VjmzSy\nQgUW90oI65HUoEAtiQx+tT4f0ZtGtCwV8HjCDcJ6r9wR5mQmjlVlYhOabDM276IB\nzFRuy5o9AgMBAAECggEAFxRy8G2y2PlPtsIyGVKIhBacs5HKwzbr/1q/FI+ZQE8g\nBp5YQCuUrqasjWa0SRoWGOqw4P6ziwMQ29A49UU+pXKIBxKLdO5xRhVcAFZuUleo\n7r+vqDcrwyL6MNPY1j9u7Xt7NWYVNJPpxqgGKmckz46pxlDoovn9+dxhPu6K7EeJ\nmtItm92XbctNfDYITF0SA9M9O41pkIZspI9cADigr3kzchqDm9KcmJjGApAr8bry\nw8JUsk4lRJiuvvzudH1DYQsEJPmO+k/Lq1fcf6cPkknILekBJGx3AvH1JBz9vAvW\n1JHQWFXACGXfagqb2BtDiLD28lWldnMkLn8IJ/DIoQKBgQD+LEhoXm4VPz03TZAc\nxvcSV/7eLBvpUbGEb1I/Hr8OI4KY5wC33osGCM59BVxVlLLh9855c0CQWK7vrPPp\no6YG4A/Xbblsz6PmHBiVpDy56VhXqH55Kx5/+ARBdS8WZa1dnT1HmjCSt1xVlNqL\n1besyVFgyDv69HeljsB0uOI/4QKBgQD1v7Vw7GwEwhuVBQlj4wG2XP3+JbDNyH13\nBEzeNXoE2hd2uL7wzUXCzDcqNBIHAvc2MrBo3eV9l09eZmv8V9YuuPWT7i0cH1uA\nIp3FUjoVgMz4QdM1+7YsdM/PdKAcDJ7+xSb81BJmq1kREZrwH7viFZEB+MkKnTCx\n1Vn0/90V3QKBgQDrL0x8jkvsCwz4vCNKDWyWo6eoKkZVWQsaEOuYjjmYupDgLHeE\nqz4WglWWZzxtz97JqkN6K4OlTPnpui4jlRJOMEtYOiYmIed1R7AT3tl16Q2eZsFI\nGvbo0DQX4XeFkOWexpzqQSkKyPF+GvMyCroe/lT3aa/eYRDIt1Mrbduj4QKBgQDG\nAbqrCwOZ7eCVeKJxRiZKDrFkRnAnzqQw8lkRLdtr72G6ee73TR4pb6v/KEdiOOSB\nWeRECo5vXCxKLpJRl2Bu8v6EPANCxo1OOBYROEiurMH6Qedxdqf5OAF88UZUc2Lk\nemwIiMNu0B8KnrnNQnR7HM9i3Fb4Y2Ep2HML8eDsTQKBgHTonsIG6aZc09IHu1pd\nNnrEN0DOvhoUzF6gSvlS/eA0arj2hKbC/TOLSKrVJnd6J4+L+tH8JPKDN2EiLXK+\nauFG1jiz7qF/doUbRXo2JnyraDjdmaCLrU1xpcLLHx5dun0YsRKwih0SIHssWL4N\nWc/qc78UeSAzPzNFz6VZ1GlZ\n-----END PRIVATE KEY-----\n",
  "client_email": "srcl-gemini-sa@canvas-sum-481614-f6.iam.gserviceaccount.com",
  "client_id": "103699972823993364807",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
  "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/srcl-gemini-sa%40canvas-sum-481614-f6.iam.gserviceaccount.com",
  "universe_domain": "googleapis.com"
}
EOF
chmod 600 ~/google_credentials.json
export GOOGLE_APPLICATION_CREDENTIALS="/home/schlieve001/google_credentials.json"
export GOOGLE_CLOUD_PROJECT="canvas-sum-481614-f6"
grep -q "GOOGLE_APPLICATION_CREDENTIALS" ~/.bashrc || echo "export GOOGLE_APPLICATION_CREDENTIALS=\"$GOOGLE_APPLICATION_CREDENTIALS\"" >> ~/.bashrc
grep -q "GOOGLE_CLOUD_PROJECT" ~/.bashrc || echo "export GOOGLE_CLOUD_PROJECT=\"$GOOGLE_CLOUD_PROJECT\"" >> ~/.bashrc
pip install google-cloud-aiplatform google-cloud-storage pillow --quiet
echo "✅ ENGINE #4 READY"
