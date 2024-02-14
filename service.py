import time
import uuid
from langchain.chains import GraphCypherQAChain, ConversationChain
from langchain.chat_models import AzureChatOpenAI, ChatVertexAI
from langchain.graphs import Neo4jGraph
from langchain.memory import ConversationSummaryBufferMemory
import streamlit as st
import os
import openai
from neo4j.exceptions import ConstraintError

import drivers


class NeoLangService:
    def __init__(self, llm_type, temperature):
        self.llm_type = llm_type
        self.temperature = temperature
        self.text_embedding_model = "textembedding-gecko@001"
        self.db_user = os.environ.get('NEO4J_USERNAME')
        self.db_password = os.environ.get('NEO4J_PASSWORD')
        self.db_uri = os.environ.get('NEO4J_URI')
        self.db_name = os.environ.get('NEO4J_DATABASE_NAME')
        self.graph = Neo4jGraph(url=self.db_uri, username=self.db_user, password=self.db_password,
                                database=self.db_name)
        self.driver = drivers.init_driver(self.db_uri, username=self.db_user,
                                          password=self.db_password)

        self.llm = self._init_llm()

    def _init_llm(self):
        if self.llm_type == "chat-bison 2k":
            return ChatVertexAI(
                model_name='chat-bison',
                max_output_tokens=2048,  # Adjusted for "2k" variant
                temperature=self.temperature,
                top_p=0.95,
                top_k=40
            )
        elif self.llm_type == "GPT-4 8k":
            return AzureChatOpenAI(
                openai_api_version=openai.api_version,
                openai_api_key=openai.api_key,
                openai_api_base=os.environ.get('OPENAI_API_BASE'),
                deployment_name=os.environ.get('GPT4_8K_NAME'),
                model_name='gpt-4',
                temperature=self.temperature
            )
        else:
            raise ValueError(f"Unsupported LLM type: {self.llm_type}")

    def get_graph_schema(self):
        """
        Retrieves the graph schema from the Neo4j database.
        """
        self.graph.refresh_schema()
        return self.graph.schema

    def generate_example_questions(self):
        """
        Generates a set of example questions for Field Service Engineer context.
        """
        return [
            "What are the configurations associated with engine serial number XYZ123?",
            "Which software components are contained in build ABC?",
            "List all ECM codes related to configuration ID 456.",
        ]

    def create_prompt(self, question: str):
        """
        Creates a prompt using GraphCypherQAChain to query the Neo4j graph with the user's question.
        """
        schema = self.get_graph_schema()
        example_questions = self.generate_example_questions()

        chain = GraphCypherQAChain.from_llm(
            llm=self.llm,
            graph=self.graph,
            verbose=True
        )

        result = chain.run(question)
        print(result)



        prompt_template = f"""
            Task: Generate Cypher statement to query a graph database.
            Schema: {schema}
            Example Questions: {', '.join(example_questions)}
            The question is: {question}
            Graph Query Results: {result}
            Answer the question using the graph query results.
            Provide explanations or sources if available.
        """

        print(prompt_template + 'this is the prompt template')
        return prompt_template

    def create_conversation(self, llm_type: str):
        """
        This function intializes a conversation with the llm.
        The resulting conversation can be prompted successively and will
        remember previous interactions.
        """
        create_conversation_timer_start = time.perf_counter()
        print("llm type: ", llm_type)
        llm = self._init_llm()

        st.session_state['llm_memory'] = ConversationSummaryBufferMemory(llm=llm, max_token_limit=1000)

        res = ConversationChain(
            llm=llm,
            memory=st.session_state['llm_memory']
        )
        print("Create conversation time: " + str(
            round(time.perf_counter() - create_conversation_timer_start, 4)) + " seconds.")

        return res

    def log_new_conversation(self, llm, user_input):
        """
        This method creates a new conversation node and logs the
        initial user message in the neo4j database.
        Appropriate relationships are created.
        """

        log_timer_start = time.perf_counter()

        print('logging new conversation...')
        messId = 'user-' + str(uuid.uuid4())
        convId = 'conv-' + str(uuid.uuid4())

        print('convId: ', convId)

        def log(tx):
            tx.run("""
            create (c:Conversation)-[:FIRST]->(m:Message)
            set c.id = $convId, c.llm = $llm,
                c.temperature = $temperature,
                c.public = toBoolean($public),
                m.id = $messId, m.content = $content,
                m.role = $role, m.postTime = datetime(),
                m.embedding = $embedding,
                m.public = toBoolean($public)

            with c
            merge (s:Session {id: $sessionId})
            on create set s.createTime = datetime()
            merge (s)-[:HAS_CONVERSATION]->(c)
                      """, convId=convId, llm=llm, messId=messId,
                   temperature=st.session_state['temperature'],
                   content=user_input, role='user', sessionId=st.session_state['session_id'],
                   embedding=st.session_state['recent_question_embedding'],
                   public=PUBLIC)

        # update the latest message in the log chain
        st.session_state['latest_message_id'] = messId

        try:
            with self.driver.session(database=self.database_name) as session:
                session.execute_write(log)

        except ConstraintError as err:
            print(err)

            session.close()

        print(
            'conversation init & user log time: ' + str(round(time.perf_counter() - log_timer_start, 4)) + " seconds.")

    def log_user(self, user_input):
        """
        This method logs a new user message to the neo4j database and
        creates appropriate relationships.
        """

        log_timer_start = time.perf_counter()
        print('logging user message...')
        prevMessId = st.session_state['latest_message_id']
        messId = 'user-' + str(uuid.uuid4())

        def log(tx):
            tx.run("""
            match (pm:Message {id: $prevMessId})
            merge (m:Message {id: $messId})
            set m.content = $content,
                m.role = $role, m.postTime = datetime(),
                m.embedding = $embedding, m.public = toBoolean($public)

            merge (pm)-[:NEXT]->(m)
                      """, prevMessId=prevMessId, messId=messId, content=user_input, role='user',
                   embedding=st.session_state['recent_question_embedding'], public=PUBLIC)

        # update the latest message in the log chain
        st.session_state['latest_message_id'] = messId

        try:
            with self.driver.session(database=self.database_name) as session:
                session.execute_write(log)

        except Neo4jError as err:
            print(err)

        print('user log time: ' + str(round(time.perf_counter() - log_timer_start, 4)) + " seconds.")

    def log_assistant(self, assistant_output, context_indices):
        """
        This method logs a new assistant message to the neo4j database and
        creates appropriate relationships.
        """

        log_timer_start = time.perf_counter()

        print('logging llm message...')
        prevMessId = st.session_state['latest_message_id']
        messId = 'llm-' + str(uuid.uuid4())

        mem = st.session_state['llm_memory'].moving_summary_buffer

        def log(tx):
            tx.run("""
            match (pm:Message {id: $prevMessId})
            merge (m:Message {id: $messId})
            set m.content = $content,
                m.role = $role, m.postTime = datetime(),
                m.numDocs = $numDocs,
                m.vectorIndexSearch = true,
                m.prompt = $prompt,
                m.public = toBoolean($public),
                m.resultingSummary = $resultingSummary

            merge (pm)-[:NEXT]->(m)

            with m
            unwind $contextIndices as contextIdx
            match (d:Document)
            where d.index = contextIdx

            with m, d
            merge (m)-[:HAS_CONTEXT]->(d)
                    """, prevMessId=str(prevMessId), messId=str(messId), content=str(assistant_output),
                   role='assistant', contextIndices=context_indices,
                   numDocs=st.session_state['num_documents_for_context'],
                   prompt=st.session_state['general_prompt'],
                   resultingSummary=mem,
                   public=PUBLIC)

        # update the latest message in the log chain
        st.session_state['latest_message_id'] = messId
        st.session_state['latest_llm_message_id'] = messId

        try:
            with self.driver.session(database=self.database_name) as session:
                session.execute_write(log)

        except ConstraintError as err:
            print(err)

        print('assistant log time: ' + str(round(time.perf_counter() - log_timer_start, 4)) + " seconds.")

    def rate_message(self, rating_dict):
        """
            This message rates an LLM message given a rating and uploads
            the rating to the database.
        """

        print('rating llm message...')
        if 'latest_llm_message_id' in st.session_state:
            rate_timer_start = time.perf_counter()

            print('updating id: ', st.session_state['latest_llm_message_id'])

            # parse rating info
            message = rating_dict['text']
            rating = 'Good' if rating_dict['score'] == '👍' else 'Bad'

            def rate(tx):
                tx.run("""
                match (m:Message {id: $messId})

                set m.rating = $rating,
                    m.ratingMessage = $message
                        """, rating=rating, message=message, messId=st.session_state['latest_llm_message_id'])

            try:
                with self.driver.session(database=self.database_name) as session:
                    session.execute_write(rate)

            except ConstraintError as err:
                print(err)

            print('assistant rate time: ' + str(round(time.perf_counter() - rate_timer_start, 4)) + " seconds.")