FROM public.ecr.aws/lambda/python:3.11

# Install GCC and SQLite 3.39+
RUN yum install -y gcc gcc-c++ make wget && \
    wget https://www.sqlite.org/2022/sqlite-autoconf-3390000.tar.gz && \
    tar xzf sqlite-autoconf-3390000.tar.gz && \
    cd sqlite-autoconf-3390000 && \
    ./configure --prefix=/var/lang && \
    make && make install && \
    cd .. && rm -rf sqlite-autoconf-3390000* && \
    yum clean all

COPY requirements_lambda.txt .

RUN pip install --no-cache-dir --timeout 600 \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    -r requirements_lambda.txt

# Install pysqlite3-binary — must be after all other packages
RUN pip install --no-cache-dir pysqlite3-binary==0.5.4

# Force cache bust — increment this when you need a fresh build
ARG CACHE_BUST=2

COPY rag.py .

CMD ["rag.lambda_handler"]