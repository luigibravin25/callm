# immagine del front-end (step 9) in due fasi: Node costruisce, nginx serve
# fase 1: dipendenze npm e build di produzione (comprende il controllo dei tipi con tsc)
FROM node:24-alpine AS build
WORKDIR /app
# prima package.json e lock: il livello di npm ci resta in cache finché non cambiano
COPY package.json package-lock.json ./
RUN npm ci
# sorgenti, test e configurazioni (tsc --noEmit li controlla tutti)
COPY . .
RUN npm run build

# fase 2: solo i file statici e la configurazione di nginx (niente Node né node_modules)
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
# file statici e proxy /api verso il back-end
COPY nginx.conf /etc/nginx/conf.d/default.conf
